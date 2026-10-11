"""PPT 相关请求/响应模型"""

from typing import Optional
from pydantic import BaseModel, Field

from app.schemas.common import PageRequest


class PptCreateRequest(BaseModel):
    """创建 PPT 请求（流式）"""

    message: str = Field(..., min_length=1, description="创作主题/需求")
    style: Optional[str] = Field(default="business", description="风格：business/creative/academic/minimalist")
    session_id: Optional[str] = Field(default=None, alias="sessionId", description="会话ID（不传则按用户隔离）")

    class Config:
        populate_by_name = True


class PptOutlineResumeRequest(BaseModel):
    """大纲审阅后续跑请求（第二段流式，扣配额）"""

    message: str = Field(..., min_length=1, description="创作主题（第一段 /ppt/create 的原 message）")
    outline: str | list = Field(
        ...,
        description="编辑后的大纲（JSON 字符串或数组，每页含 title/layout_hint/purpose）",
    )
    thread_id: Optional[str] = Field(
        default=None, alias="threadId",
        description="第一段 OUTLINE_REVIEW 返回的 thread_id（可选，A' 仅作 draft 标识/日志）",
    )
    style: Optional[str] = Field(default="business", description="风格")
    ppt_id: Optional[int] = Field(
        default=None, alias="pptId",
        description="HITL 第一段创建的任务ID（可选，传入则复用该任务续跑，不新建）",
    )

    class Config:
        populate_by_name = True


class PptListRequest(PageRequest):
    """我的 PPT 任务分页请求"""

    status: Optional[str] = Field(
        default=None, description="状态过滤：SUCCESS/IN_PROGRESS/FAILED",
    )


class PptResumeRequest(BaseModel):
    """断点续跑请求（按 pptId 注入已落库的 outline/research/filename 续跑）"""

    ppt_id: int = Field(..., alias="pptId", description="要续跑的任务ID")
    message: Optional[str] = Field(
        default=None, description="可选新主题（不传则沿用任务原 topic）",
    )

    class Config:
        populate_by_name = True
