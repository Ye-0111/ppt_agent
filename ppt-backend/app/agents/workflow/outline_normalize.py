"""用户编辑后大纲的规范化。

输入：前端编辑器回灌的脏数据（JSON 字符串 / list[dict] / dict）。
输出：规范化的 outline JSON 字符串（与 graph._extract_outline 产出同形态），
供第二段 ``Command(resume={"outline": ...})`` 回灌。

规则（对应编辑粒度"文本 + 增删页，不改 layout_hint"）：
- title 必填（空则丢弃整页）
- layout_hint 白名单 {title-slide, content, two-column}，缺失/非法补 "content"
- purpose 缺失补 ""
- 首页强制 title-slide（唯一允许改 layout_hint 的特例，保证封面语义）
- 彻底非法返回 ""，由 controller 据此拒绝（不进第二段）
"""

import json
from typing import Optional, Union

from app.tools.content_refiner import _parse_json  # 三层容错 JSON 解析

VALID_LAYOUTS = {"title-slide", "content", "two-column"}
DEFAULT_LAYOUT = "content"


def _normalize_page(page: object) -> Optional[dict]:
    """规范化单页。无标题返回 None（由调用方丢弃）。"""
    if not isinstance(page, dict):
        return None
    title = page.get("title")
    title = title.strip() if isinstance(title, str) else ""
    if not title:
        return None
    layout = page.get("layout_hint")
    if not isinstance(layout, str) or layout not in VALID_LAYOUTS:
        layout = DEFAULT_LAYOUT
    purpose = page.get("purpose")
    if not isinstance(purpose, str):
        purpose = ""
    return {"title": title, "layout_hint": layout, "purpose": purpose}


def normalize_outline(raw: Union[str, list, dict, None]) -> str:
    """规范化大纲 → JSON 字符串。非法/空输入返回 ""。"""
    if raw is None:
        return ""
    if isinstance(raw, str):
        raw = _parse_json(raw)  # 裸JSON → ```json``` 块 → [...] 子串
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return ""

    pages = [p for p in (_normalize_page(item) for item in raw) if p is not None]
    if not pages:
        return ""

    # 首页强制封面（用户增删页后仍保证首页为 title-slide）
    pages[0]["layout_hint"] = "title-slide"
    return json.dumps(pages, ensure_ascii=False)
