"""对话请求/响应模型"""

from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """对话请求"""

    message: str = Field(..., min_length=1, description="用户消息")
    session_id: Optional[str] = Field(
        default=None,
        description="会话 ID，用于多用户隔离。不传则使用默认会话",
    )


class ChatResponse(BaseModel):
    """对话响应"""

    reply: str = Field(..., description="模型回复")
    session_id: str = Field(..., description="本次使用的会话 ID")


class ClearHistoryRequest(BaseModel):
    """清除历史请求"""

    session_id: str = Field(..., description="要清除历史的会话 ID")
