"""PPT 模板工具 - 基于 {{variable}} 占位符的模板扫描与渲染。

- ``render_ppt_template`` — 用变量值替换模板里的 ``{{placeholder}}``，导出一份新 PPTX。
  支持同段多占位符 + 普通文字混排；缺值的占位符原样保留并在返回里报告。
- ``scan_template_placeholders`` — 打开一个 PPTX，返回其中所有 ``{{占位符}}`` 名称；
  供上传接口校验「是否为含占位符的成品模板」。

模板需在 PowerPoint 等工具里手工编辑：把要动态变化的文本写成 ``{{占位符}}``。本模块只负责
扫描与渲染，不负责把普通 PPTX 自动抽成模板。

占位符约定：``{{`` + 名称（``\\w``：中/英/数字/下划线，**不能含空格/标点/连字符**）+ ``}}``，
名称两侧允许空白，如 ``{{ title }}``、``{{ 标题 }}``。
"""

import json
import logging
import re
from pathlib import Path

from langchain_core.tools import tool
from pptx import Presentation

from app.core.config import settings
from app.tools._ppt_lock import ppt_file_lock

logger = logging.getLogger(__name__)

# {{ name }} —— 名称只允许 \w（字母数字下划线，Unicode 含中文），两侧允许空白
_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _resolve_ppt_path(filename: str, subdir: str = "ppt_output") -> Path:
    """PPTX 路径解析。默认 workspace/ppt_output/；上传的成品模板放 workspace/ppt_templates/。"""
    return settings.workspace_path / subdir / filename


def _iter_text_frames(prs):
    """遍历整份 PPTX 的所有 text_frame：递归进组合形状（group）与表格单元格。

    yield (slide_index, text_frame)。
    """
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    def _walk(shapes, slide_index):
        for shape in shapes:
            try:
                if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                    yield from _walk(shape.shapes, slide_index)
                elif getattr(shape, "has_table", False) and shape.has_table:
                    for row in shape.table.rows:
                        for cell in row.cells:
                            yield slide_index, cell.text_frame
                elif getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                    yield slide_index, shape.text_frame
            except Exception:
                # 个别形状访问异常不阻断整体遍历
                continue

    for idx, slide in enumerate(prs.slides):
        yield from _walk(slide.shapes, idx)


def _set_paragraph_text(paragraph, text: str) -> None:
    """重设段落文本，尽量保留首个 run 的字体格式。

    多 run 时把文本写入 runs[0]、其余 run 清空（保留 runs[0] 的字号/颜色/粗体）；
    无 run（空段落）时退化为 ``paragraph.text =`` 新建一个默认 run。
    """
    runs = paragraph.runs
    if runs:
        runs[0].text = text
        for r in runs[1:]:
            r.text = ""
    else:
        paragraph.text = text


def _collect_placeholder_tokens(prs) -> set:
    """扫描整份 PPTX，收集所有 {{placeholder}} 名称（渲染前用于报告缺失/未用变量）。"""
    tokens = set()
    for _, tf in _iter_text_frames(prs):
        for p in tf.paragraphs:
            for m in _PLACEHOLDER_RE.finditer(p.text):
                tokens.add(m.group(1))
    return tokens


def scan_template_placeholders(file_path) -> list[str]:
    """打开一个 PPTX 文件，返回其中所有 {{占位符}} 名称（去重、保持发现顺序）。

    供上传接口校验「是否为含占位符的成品模板」；空列表表示无占位符。
    """
    prs = Presentation(str(file_path))
    seen: list[str] = []
    for name in _collect_placeholder_tokens(prs):
        if name not in seen:
            seen.append(name)
    return seen


@tool
async def render_ppt_template(
    template_filename: str,
    variables: str = "{}",
    output_filename: str = "",
    source_dir: str = "ppt_output",
) -> str:
    """用变量值替换模板里的 {{占位符}}，导出一份新 PPTX。

    支持同一段落内多占位符与普通文字混排（如 ``{{title}}：{{author}}``）。
    缺值的占位符原样保留（``{{name}}`` 不变），并在返回的 ``missing_variables`` 里报告；
    传了但模板里没有的变量在 ``unused_variables`` 里报告。

    Args:
        template_filename: 模板 PPTX 文件名
        variables: JSON 字符串，占位名 -> 值（非字符串会自动转字符串）
        output_filename: 输出文件名；留空则 ``{模板名}_rendered.pptx``
        source_dir: 模板所在子目录（workspace 下，默认 ``ppt_output``）；
            上传的成品模板用 ``ppt_templates``。渲染产物**始终写 ppt_output/**（走既有下载接口）。

    Returns:
        JSON 字符串：``{success, output_filename, substituted, missing_variables, unused_variables}``
    """
    try:
        if isinstance(variables, dict):
            var_map = variables
        else:
            var_map = json.loads(variables) if variables else {}
        # 值统一转字符串（数字/布尔等）
        var_map = {k: ("" if v is None else str(v)) for k, v in var_map.items()}

        src = _resolve_ppt_path(template_filename, source_dir)
        if not src.exists():
            return f"错误：模板文件不存在: {template_filename}"

        out_name = output_filename or f"{src.stem}_rendered.pptx"
        out_path = _resolve_ppt_path(out_name, "ppt_output")

        prs = Presentation(str(src))

        # 先采集模板里的全部占位符名（渲染前），用于事后报告缺失/未用
        template_tokens = _collect_placeholder_tokens(prs)
        substituted: list[str] = []

        def _repl(m: re.Match) -> str:
            name = m.group(1)
            if name in var_map:
                if name not in substituted:
                    substituted.append(name)
                return var_map[name]
            return m.group(0)  # 缺值：原样保留

        for _, tf in _iter_text_frames(prs):
            for p in tf.paragraphs:
                if "{{" not in p.text:
                    continue
                new_text = _PLACEHOLDER_RE.sub(_repl, p.text)
                if new_text != p.text:
                    _set_paragraph_text(p, new_text)

        missing = sorted(template_tokens - set(var_map.keys()))
        unused = sorted(set(var_map.keys()) - template_tokens)

        async with ppt_file_lock(out_name):
            prs.save(str(out_path))

        result = {
            "success": True,
            "output_filename": out_name,
            "substituted": substituted,
            "missing_variables": missing,
            "unused_variables": unused,
            "message": (
                f"模板渲染成功: {out_name}，替换 {len(substituted)} 个变量；"
                f"缺值 {len(missing)} 个，未用 {len(unused)} 个"
            ),
        }
        logger.info("模板渲染: %s, 替换 %d, 缺 %d, 未用 %d",
                    out_name, len(substituted), len(missing), len(unused))
        return json.dumps(result, ensure_ascii=False)

    except json.JSONDecodeError as e:
        return f"错误：variables JSON 解析失败: {e}"
    except Exception as e:
        logger.error("render_ppt_template 失败: %s", e)
        return f"错误：模板渲染失败: {e}"
