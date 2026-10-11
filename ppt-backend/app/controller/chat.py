"""对话控制器"""

import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas.chat import ChatRequest, ClearHistoryRequest
from app.schemas.common import BaseResponse
from app.core.sse import sse_event, SSE_HEADERS
from app.agent import default_chat_agent

router = APIRouter(prefix="/chat", tags=["对话"])
logger = logging.getLogger(__name__)


@router.post("", response_model=BaseResponse)
async def chat(req: ChatRequest):
    """与大模型对话（纯聊天 agent，不走多智能体路由）"""
    reply = await default_chat_agent.run(
        user_message=req.message,
        session_id=req.session_id,
    )
    return BaseResponse.success(
        data={
            "reply": reply,
            "session_id": req.session_id or "default",
        }
    )


@router.post("/stream")
async def chat_stream(req: ChatRequest):
    """与大模型对话（流式 SSE 模式）"""
    session_id = req.session_id or "default"

    async def event_generator():
        try:
            async for event in default_chat_agent.run_stream(
                user_message=req.message,
                session_id=session_id,
            ):
                yield sse_event(event["event"], event["data"])
        except Exception as e:
            logger.error("[流式对话] 未捕获异常: %s", e)
            yield sse_event("ERROR", {"message": f"服务器异常: {e}"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/clear", response_model=BaseResponse)
async def clear_history(req: ClearHistoryRequest):
    """清除指定会话的历史记录"""
    await default_chat_agent.clear_history(session_id=req.session_id)
    return BaseResponse.success(message="历史记录已清除")
