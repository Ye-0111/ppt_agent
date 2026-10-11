"""普通聊天 Agent — 纯 LLM 对话 + 记忆，不走多智能体路由（不触发 PPT 生成）。

供 /chat、/chat/stream 专用，避免 intent_router 在闲聊中误判为 create 触发 generate_ppt。
对外接口与 MultiAgent 一致：run / run_stream / clear_history，便于 controller 统一调用。
"""

import logging
import time
from typing import AsyncIterator, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.observability import apply_trace_context
from app.agents.common.llm import build_llm, build_summary_llm
from app.schemas.events import AGENT_THINKING, DONE, ERROR, TEXT_DELTA, make_event
from app.utils.memory import SummaryBufferMemory

logger = logging.getLogger(__name__)

_CHAT_SYSTEM_PROMPT = (
    "你是 PPTCreator 助手。与用户进行自然、简洁、专业的中文对话。"
    "本接口仅负责闲聊与答疑，不直接生成 PPT；若用户想创建 PPT，请引导其使用 PPT 创作功能。"
)


class PlainChatAgent:
    """纯聊天 agent：一次 LLM 调用 + SummaryBufferMemory，不经 StateGraph / intent_router。"""

    def __init__(self):
        self.llm = build_llm()
        self.memory = SummaryBufferMemory(summary_llm=build_summary_llm())
        logger.info("PlainChatAgent 初始化完成（纯聊天，不走多智能体路由）")

    @staticmethod
    def _build_messages(user_message: str, history: list) -> list:
        return [
            SystemMessage(content=_CHAT_SYSTEM_PROMPT),
            *history,
            HumanMessage(content=user_message),
        ]

    async def run(
        self, user_message: str, session_id: Optional[str] = None,
        trace_meta: Optional[dict] = None,
    ) -> str:
        session_id = session_id or "default"
        logger.info("[PlainChat] 会话 %s 收到消息: %s", session_id, user_message[:100])
        history = await self.memory.load(session_id)
        try:
            config = apply_trace_context(
                None,
                metadata={
                    "session_id": session_id, "intent": "chat", **(trace_meta or {}),
                },
                tags=["chat"],
                run_name="聊天",
            )
            ai = await self.llm.ainvoke(
                self._build_messages(user_message, history), config=config
            )
            reply = ai.content if isinstance(ai.content, str) else str(ai.content)
        except Exception as e:
            logger.error("[PlainChat] 异常: %s", e)
            reply = f"抱歉，处理时出错了: {e}"
        await self.memory.save(session_id, user_message, reply)
        return reply

    async def run_stream(
        self, user_message: str, session_id: Optional[str] = None,
        trace_meta: Optional[dict] = None,
    ) -> AsyncIterator[dict]:
        session_id = session_id or "default"
        start = time.time()
        logger.info("[PlainChat/流式] 会话 %s 收到消息: %s", session_id, user_message[:100])

        yield make_event(AGENT_THINKING, {"message": "正在思考..."})
        response_parts: list[str] = []
        try:
            history = await self.memory.load(session_id)
            config = apply_trace_context(
                None,
                metadata={
                    "session_id": session_id, "intent": "chat", **(trace_meta or {}),
                },
                tags=["chat"],
                run_name="聊天",
            )
            async for chunk in self.llm.astream(
                self._build_messages(user_message, history), config=config
            ):
                content = getattr(chunk, "content", "") or ""
                if content:
                    response_parts.append(content)
                    yield make_event(TEXT_DELTA, {"content": content})
            await self.memory.save(session_id, user_message, "".join(response_parts))
        except Exception as e:
            logger.error("[PlainChat/流式] 异常: %s", e)
            yield make_event(ERROR, {"message": f"执行异常: {e}"})
        finally:
            yield make_event(
                DONE,
                {"session_id": session_id, "elapsed_seconds": round(time.time() - start, 2)},
            )

    async def clear_history(self, session_id: str):
        await self.memory.clear(session_id)
        logger.info("[PlainChat] 会话 %s 历史已清除", session_id)
