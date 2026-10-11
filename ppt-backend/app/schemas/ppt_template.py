"""PPT 模板请求模型"""

from typing import Optional
from pydantic import BaseModel, Field

from app.schemas.common import PageRequest


class TemplateListRequest(PageRequest):
    """模板列表（分页）。scope: mine / public / all（默认 all = 自己 + 公开）。"""

    scope: Optional[str] = Field(default="all", description="范围：mine/public/all")


class TemplateCreateRequest(BaseModel):
    """选择模板创作 PPT（SSE）：AI 按主题自动填占位符。"""

    template_id: int = Field(..., alias="templateId", description="模板ID")
    message: str = Field(..., min_length=1, description="创作主题/需求")
    style: Optional[str] = Field(default="business", description="风格（预留）")

    class Config:
        populate_by_name = True
