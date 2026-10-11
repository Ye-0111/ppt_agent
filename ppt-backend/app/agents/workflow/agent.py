"""workflow 模式入口 — Custom workflow（StateGraph + Supervisor 路由）。

对外方法签名与 SubAgents / 旧 PPTAgent / LangChainAgent 完全一致：
  - run(user_message, session_id) -> str
  - run_stream(user_message, session_id) -> AsyncIterator[dict]
  - run_ppt_stream(user_message, session_id, on_ppt_created) -> AsyncIterator[dict]
  - clear_history(session_id)
"""

import logging
import time
import uuid
from typing import AsyncIterator, Awaitable, Callable, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core.config import settings
from app.core.observability import apply_trace_context
from app.schemas.events import (
    AGENT_THINKING,
    DONE,
    ERROR,
    OUTLINE_REVIEW,
    TEXT_DELTA,
    make_event,
)
from app.utils.memory import SummaryBufferMemory

from app.agents.common.llm import build_llm, build_summary_llm
from app.agents.workflow.graph import (
    build_create_pipeline,
    build_graph,
    build_outline_only_graph,
)
from app.agents.workflow.streaming import stream_events_to_sse

# 导入 GraphRecursionError（langgraph 1.x）
try:
    from langgraph.errors import GraphRecursionError
except ImportError:  # 兜底：旧版本路径
    from langgraph.graph.exc import GraphRecursionError  # type: ignore

logger = logging.getLogger(__name__)

# 多智能体团队总览提示（作为消息流开头的 SystemMessage）
_OVERVIEW_PROMPT = (
    "你是 PPTCreator 多智能体团队（协调员 + 内容/配图/图表/美化专家）。"
    "请通过协作完成用户需求，用简洁专业的中文汇报。"
)


class MultiAgent:
    """workflow 模式：Supervisor + 4 Specialist（Custom workflow）。"""

    def __init__(self):
        from langgraph.checkpoint.memory import MemorySaver

        self.llm = build_llm()
        self.memory = SummaryBufferMemory(summary_llm=build_summary_llm())
        self.recursion_limit = settings.agent_multi_recursion_limit
        # 主图：存量单段 create/chat/enhance/analyze 流程（不依赖 checkpointer）
        self.graph = build_graph(self.llm)
        # HITL 第一段：仅 outline 子图（带 checkpointer，供 aget_state 取大纲）
        self.outline_graph = build_outline_only_graph(self.llm, checkpointer=MemorySaver())
        # HITL 第二段：create_pipeline 子图（入口条件边跳过 outline，注入编辑后大纲直奔 research）
        self.create_pipeline = build_create_pipeline(self.llm)
        logger.info(
            "MultiAgent(workflow) 初始化完成 (supervisor + outline/content/image/chart/beautify), "
            "recursion_limit=%d, outline_review=%s",
            self.recursion_limit, settings.outline_review_enabled,
        )

    # ============================================================
    # 非流式
    # ============================================================
    async def run(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        trace_meta: Optional[dict] = None,
    ) -> str:
        session_id = session_id or "default"
        logger.info("[MultiAgent] 会话 %s 收到消息: %s", session_id, user_message[:100])

        history = await self.memory.load(session_id)
        state = self._init_state(user_message, session_id, history)

        try:
            config = apply_trace_context(
                {"recursion_limit": self.recursion_limit},
                metadata={"session_id": session_id, **(trace_meta or {})},
                tags=["multi-agent"],
                run_name="对话",
            )
            final = await self.graph.ainvoke(state, config)
        except GraphRecursionError:
            logger.error("[MultiAgent] 超出最大推理步数")
            return "抱歉，任务过于复杂，已达到最大推理步数限制，请尝试简化需求。"

        reply = self._last_ai_text(final)
        await self.memory.save(session_id, user_message, reply)
        return reply

    # ============================================================
    # 流式（对话）
    # ============================================================
    async def run_stream(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        trace_meta: Optional[dict] = None,
    ) -> AsyncIterator[dict]:
        async for event in self._stream(
            user_message, session_id, None, trace_meta=trace_meta
        ):
            yield event

    # ============================================================
    # 流式（PPT 创作，透传 on_ppt_created 回调）
    # ============================================================
    async def run_ppt_stream(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        on_ppt_created: Optional[Callable[[str], Awaitable[None]]] = None,
        style: str = "business",
        on_stage: Optional[Callable[[str, str], Awaitable[None]]] = None,
        trace_meta: Optional[dict] = None,
    ) -> AsyncIterator[dict]:
        async for event in self._stream(
            user_message, session_id, on_ppt_created, style,
            on_stage=on_stage, trace_meta=trace_meta,
        ):
            yield event

    # ============================================================
    # HITL 第一段：跑 outline specialist，产出 OUTLINE_REVIEW 事件
    # ============================================================
    async def run_outline_stream(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        style: str = "business",
        on_stage: Optional[Callable[[str, str], Awaitable[None]]] = None,
        trace_meta: Optional[dict] = None,
    ) -> AsyncIterator[dict]:
        """大纲人工审阅第一段：跑 outline_only 子图生成大纲，推送 OUTLINE_REVIEW。

        应用层方案（不依赖 langgraph interrupt）：单独跑 outline specialist，大纲生成后
        流自然结束，从 agent_state 取 outline。不扣配额、不写记忆（大纲非最终回复）。
        DONE 携带 thread_id 供第二段作 draft 标识（A' 不用于 resume）。
        """
        session_id = session_id or "default"
        thread_id = f"{session_id}-{uuid.uuid4().hex[:12]}"
        configurable: dict = {"thread_id": thread_id}
        if on_stage:
            configurable["on_stage"] = on_stage  # outline 节点产出实时落库（断点恢复）
        config = apply_trace_context(
            {
                "configurable": configurable,
                "recursion_limit": self.recursion_limit,
            },
            metadata={
                "session_id": session_id, "style": style,
                "intent": "create", **(trace_meta or {}),
            },
            tags=["ppt-create", "hitl"],
            run_name="大纲审阅",
        )
        start = time.time()
        logger.info(
            "[MultiAgent/HITL-1] 会话 %s 收到消息: %s (thread=%s)",
            session_id, user_message[:100], thread_id,
        )

        yield make_event(AGENT_THINKING, {"message": "正在生成大纲..."})

        try:
            history = await self.memory.load(session_id)
            state = self._init_state(user_message, session_id, history, style)

            async for event in stream_events_to_sse(
                self.outline_graph, state, self.recursion_limit,
                on_ppt_created=None, config=config,
            ):
                yield event

            # outline_only 跑完，从 checkpoint 取大纲
            snap = await self.outline_graph.aget_state(config)
            outline = snap.values.get("outline") if snap else None
            if not outline:
                logger.warning("[MultiAgent/HITL-1] 未生成大纲")
                yield make_event(ERROR, {"message": "大纲生成失败，请重试"})
                return
            yield make_event(OUTLINE_REVIEW, {"outline": outline, "thread_id": thread_id})
        except GraphRecursionError:
            logger.error("[MultiAgent/HITL-1] 超出最大推理步数")
            yield make_event(ERROR, {"message": "超出最大推理步数限制"})
        except Exception as e:
            logger.error("[MultiAgent/HITL-1] 执行异常: %s", e)
            yield make_event(ERROR, {"message": f"执行异常: {e}"})
        finally:
            logger.info(
                "[MultiAgent/HITL-1] 会话 %s 完成, 耗时 %.2fs",
                session_id, time.time() - start,
            )
            yield make_event(DONE, {"session_id": session_id, "thread_id": thread_id})

    # ============================================================
    # HITL 第二段：注入编辑后大纲，跑 create_pipeline 生成 PPT
    # ============================================================
    async def run_create_stream(
        self,
        user_message: str,
        session_id: Optional[str],
        outline: str,
        on_ppt_created: Optional[Callable[[str], Awaitable[None]]] = None,
        style: str = "business",
        on_stage: Optional[Callable[[str, str], Awaitable[None]]] = None,
        trace_meta: Optional[dict] = None,
    ) -> AsyncIterator[dict]:
        """大纲人工审阅第二段：把编辑后的大纲注入 state.outline，跑 create_pipeline 子图。

        create_pipeline 入口条件边 route_create_start 检测到 outline → 跳过 outline 节点
        直奔 research→content→[image‖chart]→beautify。outline 应为 normalize_outline 规范化后
        的 JSON 字符串。
        """
        session_id = session_id or "default"
        start = time.time()
        response_parts: list[str] = []
        logger.info("[MultiAgent/HITL-2] 会话 %s 注入大纲续跑 create_pipeline", session_id)

        yield make_event(AGENT_THINKING, {"message": "根据修改后的大纲继续生成..."})

        try:
            history = await self.memory.load(session_id)
            state = self._init_state(user_message, session_id, history, style)
            state["outline"] = outline  # 注入编辑后的大纲

            base = {"configurable": {"on_stage": on_stage}} if on_stage else None
            config = apply_trace_context(
                base,
                metadata={
                    "session_id": session_id, "style": style,
                    "intent": "create", **(trace_meta or {}),
                },
                tags=["ppt-create", "hitl"],
                run_name="大纲续跑",
            )
            async for event in stream_events_to_sse(
                self.create_pipeline, state, self.recursion_limit,
                on_ppt_created=on_ppt_created, config=config,
            ):
                if event["event"] == TEXT_DELTA:
                    response_parts.append(event["data"].get("content", ""))
                yield event
        except GraphRecursionError:
            logger.error("[MultiAgent/HITL-2] 超出最大推理步数")
            yield make_event(ERROR, {"message": "超出最大推理步数限制"})
        except Exception as e:
            logger.error("[MultiAgent/HITL-2] 执行异常: %s", e)
            yield make_event(ERROR, {"message": f"执行异常: {e}"})
        finally:
            response_text = "".join(response_parts)
            if response_text:
                try:
                    await self.memory.save(session_id, user_message, response_text)
                except Exception as e:
                    logger.error("[MultiAgent/HITL-2] 保存记忆失败: %s", e)
            logger.info(
                "[MultiAgent/HITL-2] 会话 %s 完成, 耗时 %.2fs",
                session_id, time.time() - start,
            )
            yield make_event(DONE, {"session_id": session_id})

    # ============================================================
    # 断点续跑：注入已落库的 outline/research/filename，由 route_create_resume 跳过已完成阶段
    # ============================================================
    async def run_resume_stream(
        self,
        user_message: str,
        session_id: Optional[str],
        resume_patch: dict,
        on_ppt_created: Optional[Callable[[str], Awaitable[None]]] = None,
        on_stage: Optional[Callable[[str, str], Awaitable[None]]] = None,
        style: str = "business",
        trace_meta: Optional[dict] = None,
    ) -> AsyncIterator[dict]:
        """断点续跑：把已落库的 outline/research/filename 注入 state，由 route_create_resume
        决定起点（filename 在→美化链；research 在→content；outline 在→research；都没有→outline）。
        结构与 run_create_stream 一致（finally 存记忆 + DONE）。
        """
        session_id = session_id or "default"
        start = time.time()
        response_parts: list[str] = []
        logger.info(
            "[MultiAgent/Resume] 会话 %s 注入续跑补丁 keys=%s",
            session_id, [k for k, v in resume_patch.items() if v],
        )

        yield make_event(AGENT_THINKING, {"message": "从上次断点继续生成..."})

        try:
            history = await self.memory.load(session_id)
            state = self._init_state(user_message, session_id, history, style)
            # 仅注入非空字段，避免把 None 覆盖进 state
            state.update({k: v for k, v in resume_patch.items() if v})

            base = {"configurable": {"on_stage": on_stage}} if on_stage else None
            config = apply_trace_context(
                base,
                metadata={
                    "session_id": session_id, "style": style,
                    "intent": "create", **(trace_meta or {}),
                },
                tags=["ppt-create", "resume"],
                run_name="断点续跑",
            )
            async for event in stream_events_to_sse(
                self.create_pipeline, state, self.recursion_limit,
                on_ppt_created=on_ppt_created, config=config,
            ):
                if event["event"] == TEXT_DELTA:
                    response_parts.append(event["data"].get("content", ""))
                yield event
        except GraphRecursionError:
            logger.error("[MultiAgent/Resume] 超出最大推理步数")
            yield make_event(ERROR, {"message": "超出最大推理步数限制"})
        except Exception as e:
            logger.error("[MultiAgent/Resume] 执行异常: %s", e)
            yield make_event(ERROR, {"message": f"执行异常: {e}"})
        finally:
            response_text = "".join(response_parts)
            if response_text:
                try:
                    await self.memory.save(session_id, user_message, response_text)
                except Exception as e:
                    logger.error("[MultiAgent/Resume] 保存记忆失败: %s", e)
            logger.info(
                "[MultiAgent/Resume] 会话 %s 完成, 耗时 %.2fs",
                session_id, time.time() - start,
            )
            yield make_event(DONE, {"session_id": session_id})

    # ============================================================
    # 流式核心
    # ============================================================
    async def _stream(
        self,
        user_message: str,
        session_id: Optional[str],
        on_ppt_created: Optional[Callable[[str], Awaitable[None]]],
        style: str = "business",
        on_stage: Optional[Callable[[str, str], Awaitable[None]]] = None,
        trace_meta: Optional[dict] = None,
    ) -> AsyncIterator[dict]:
        session_id = session_id or "default"
        start = time.time()
        response_parts: list[str] = []

        logger.info(
            "[MultiAgent/流式] 会话 %s 收到消息: %s", session_id, user_message[:100]
        )

        yield make_event(AGENT_THINKING, {"message": "多智能体团队开始协作..."})

        try:
            history = await self.memory.load(session_id)
            state = self._init_state(user_message, session_id, history, style)
            # 断点恢复：把 on_stage 回调经 config 透传给 specialist 节点（落库进度）
            base = {"configurable": {"on_stage": on_stage}} if on_stage else None
            config = apply_trace_context(
                base,
                metadata={
                    "session_id": session_id, "style": style,
                    "intent": "create", **(trace_meta or {}),
                },
                tags=["ppt-create"],
                run_name="PPT创作",
            )

            async for event in stream_events_to_sse(
                self.graph, state, self.recursion_limit, on_ppt_created, config=config,
            ):
                # 收集文本片段，用于结束后写回记忆
                if event["event"] == TEXT_DELTA:
                    response_parts.append(event["data"].get("content", ""))
                yield event

        except GraphRecursionError:
            logger.error("[MultiAgent/流式] 超出最大推理步数")
            yield make_event(ERROR, {"message": "超出最大推理步数限制"})
        except Exception as e:
            logger.error("[MultiAgent/流式] 执行异常: %s", e)
            yield make_event(ERROR, {"message": f"执行异常: {e}"})
        finally:
            # 保存记忆（失败不影响已推送的事件）
            response_text = "".join(response_parts)
            if response_text:
                try:
                    await self.memory.save(session_id, user_message, response_text)
                except Exception as e:
                    logger.error("[MultiAgent/流式] 保存记忆失败: %s", e)
            logger.info(
                "[MultiAgent/流式] 会话 %s 完成, 耗时 %.2fs",
                session_id, time.time() - start,
            )
            yield make_event(
                DONE,
                {
                    "session_id": session_id,
                    "elapsed_seconds": round(time.time() - start, 2),
                },
            )

    # ============================================================
    # 清除历史
    # ============================================================
    async def clear_history(self, session_id: str):
        await self.memory.clear(session_id)
        logger.info("[MultiAgent] 会话 %s 历史已清除", session_id)

    # ============================================================
    # 辅助
    # ============================================================
    @staticmethod
    def _init_state(
        user_message: str, session_id: str, history: list, style: str = "business"
    ) -> dict:
        """构造初始 AgentState。"""
        messages = [SystemMessage(content=_OVERVIEW_PROMPT)]
        messages.extend(history)
        messages.append(HumanMessage(content=user_message))
        return {
            "messages": messages,
            "next": None,
            "intent": None,
            "outline": None,
            "research": None,
            "filename": None,
            "style": style,
            "user_message": user_message,
            "session_id": session_id,
        }

    @staticmethod
    def _last_ai_text(final_state: dict) -> str:
        """从最终 state 取最后一条有内容的 AIMessage 文本。"""
        for msg in reversed(final_state.get("messages", [])):
            if isinstance(msg, AIMessage) and isinstance(msg.content, str):
                if msg.content.strip():
                    return msg.content
        return "任务执行完成，但未生成文字回复。"
