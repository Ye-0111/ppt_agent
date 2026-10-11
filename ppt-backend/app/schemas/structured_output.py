"""结构化输出 Schema 定义 — 三种方式的示例"""

from pydantic import BaseModel, Field
from typing import TypedDict


class TaskClassification(BaseModel):
    """PPT 任务分类结果 — 使用 Pydantic BaseModel"""
    is_complex: bool = Field(description="是否为复杂任务（需要规划多步骤）")
    reason: str = Field(default="", description="分类理由，一句话说明")
    suggested_tools: list[str] = Field(
        default_factory=list,
        description="建议使用的工具列表，如 ['refine_content', 'generate_ppt', 'enhance_ppt']",
    )


class PlanStep(TypedDict):
    """单个执行步骤"""
    description: str            # 步骤描述
    expected_tools: list[str]   # 预期使用的工具


class ExecutionPlan(TypedDict):
    """PPT 执行计划"""
    task_summary: str                    # 任务摘要
    steps: list[PlanStep]                # 步骤列表
    estimated_difficulty: str            # 预估难度: easy / medium / hard

PPT_SLIDES_SCHEMA: dict = {
    "title": "PPTSlides",
    "description": "PPT 幻灯片结构化数据，由多张幻灯片组成",
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "PPT 整体标题",
        },
        "style": {
            "type": "string",
            "enum": ["business", "creative", "academic", "minimalist"],
            "description": "PPT 主题风格",
        },
        "slides": {
            "type": "array",
            "items": {
            },
            "description": "幻灯片列表",
        },
    },
    "required": ["title", "style", "slides"],
}
