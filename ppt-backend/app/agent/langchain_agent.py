"""LangChain Agent - 基于 langgraph 的 ReAct 智能体"""

import json
import logging
import os
import time
from typing import Optional, AsyncIterator, Callable, Awaitable

from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from app.core.config import settings
from app.tools import all_tools
from app.utils.memory import SummaryBufferMemory
from app.agent.prompts import SYSTEM_PROMPT
from app.schemas.events import (
    make_event,
    AGENT_THINKING,
    TOOL_CALL,
    TOOL_RESULT,
    TEXT_DELTA,
    ERROR,
    DONE,
)

logger = logging.getLogger(__name__)

# DashScope 兼容 OpenAI 的 API 地址
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# SSE 工具结果展示的最大长度（超出截断，避免单个事件过大）
TOOL_RESULT_PREVIEW_LEN = 500


def _truncate(text: str, limit: int = TOOL_RESULT_PREVIEW_LEN) -> str:
    """截断过长的工具结果，供 SSE 事件展示"""
    if text is None:
        return ""
    return text if len(text) <= limit else text[:limit] + "...(已截断)"


class LangChainAgent:
    """LangChain 智能体（基于 langgraph create_agent / create_react_agent）"""

    def __init__(self):
        # 1. LLM
        self.llm = ChatOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=DASHSCOPE_BASE_URL,
            model=settings.dashscope_model,
            temperature=0.7,
        )

        # 2. 摘要 LLM
        summary_llm = ChatOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=DASHSCOPE_BASE_URL,
            model=settings.dashscope_model,
            temperature=0.0,
        )

        # 3. 记忆组件
        self.memory = SummaryBufferMemory(summary_llm=summary_llm)

        # 4. 创建 ReAct agent
        #    create_agent 内部自动处理 Think → Act → Observe 循环
        self.agent = create_agent(
            model=self.llm,
            tools=all_tools,
            system_prompt=SYSTEM_PROMPT,
        )

        logger.info("LangChain Agent 初始化完成 (langchain create_agent)")

    async def run(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        trace_meta: Optional[dict] = None,
    ) -> str:
        """运行 LangChain 智能体

        Args:
            user_message: 用户消息
            session_id: 会话 ID

        Returns:
            回复文本
        """
        session_id = session_id or "default"

        logger.info(
            "[LangChain Agent] 会话 %s 收到消息: %s",
            session_id, user_message[:100],
        )

        # 1. 加载记忆
        history = await self.memory.load(session_id)

        # 2. 构建消息列表
        messages = []
        messages.extend(history)
        messages.append(HumanMessage(content=user_message))

        # 3. 调用 langgraph agent（自动 ReAct 循环）
        result = await self.agent.ainvoke(
            {"messages": messages},
        )

        # 4. 提取最终回复（最后一条 AI 消息）
        final_reply = ""
        for msg in reversed(result.get("messages", [])):
            if hasattr(msg, "content") and msg.type == "ai":
                # 跳过只有 tool_calls 没有文字的中间消息
                if msg.content and msg.content.strip():
                    final_reply = msg.content
                    break

        if not final_reply:
            final_reply = "任务执行完成，但未生成文字回复。"

        # 5. 保存记忆
        await self.memory.save(session_id, user_message, final_reply)

        logger.info("[LangChain Agent] 会话 %s 完成", session_id)
        return final_reply

    # ================================================================
    # 流式入口（SSE）— 基于 langgraph agent 的 astream_events
    # ================================================================

    async def _stream_core(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        on_ppt_created: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> AsyncIterator[dict]:
        """流式核心实现 — 基于 langgraph agent 的 astream_events(version="v2")。

        对外不要直接调用，请用 run_stream（基础对话）或 run_ppt_stream（PPT 创作）。

        将底层 Runnable 事件映射为 SSE 业务事件：
        - on_chat_model_stream → TEXT_DELTA（逐 token）
        - on_tool_start        → TOOL_CALL
        - on_tool_end          → TOOL_RESULT

        Args:
            on_ppt_created: 可选异步回调。当 generate_ppt 工具成功执行时，
                以生成的文件名调用，由控制器完成配额扣减与记录（agent 不碰 DB）。

        Yields:
            {"event": <事件类型>, "data": <dict>} — 由控制器转为 SSE 格式
        """
        session_id = session_id or "default"
        start = time.time()
        response_parts: list[str] = []

        logger.info(
            "[LangChain Agent/流式] 会话 %s 收到消息: %s",
            session_id, user_message[:100],
        )

        try:
            # 1. 加载记忆
            yield make_event(AGENT_THINKING, {"message": "正在加载对话历史..."})
            history = await self.memory.load(session_id)

            # 2. 构建消息
            messages = list(history)
            messages.append(HumanMessage(content=user_message))

            yield make_event(AGENT_THINKING, {"message": "正在思考..."})

            # 3. 订阅 agent 事件流（自动 ReAct 循环）
            async for ev in self.agent.astream_events(
                {"messages": messages}, version="v2"
            ):
                kind = ev["event"]

                if kind == "on_chat_model_stream":
                    chunk = ev["data"].get("chunk")
                    content = getattr(chunk, "content", "") if chunk else ""
                    if content:
                        response_parts.append(content)
                        yield make_event(TEXT_DELTA, {"content": content})

                elif kind == "on_tool_start":
                    tool_input = ev["data"].get("input")
                    yield make_event(
                        TOOL_CALL,
                        {
                            "tool": ev["name"],
                            "args": tool_input if isinstance(tool_input, dict)
                            else {"input": tool_input},
                        },
                    )

                elif kind == "on_tool_end":
                    output = ev["data"].get("output")
                    # output 通常是 ToolMessage，取其 content；否则直接字符串化
                    content = getattr(output, "content", None)
                    result_str = content if content else (str(output) if output is not None else "")
                    yield make_event(
                        TOOL_RESULT,
                        {"tool": ev["name"], "result": _truncate(result_str)},
                    )

                    # generate_ppt 成功 → 触发回调（控制器侧完成扣减+记录）
                    if ev["name"] == "generate_ppt" and on_ppt_created is not None:
                        try:
                            result_obj = json.loads(result_str)
                            if isinstance(result_obj, dict) and result_obj.get("success") is True:
                                file_path = result_obj.get("file_path", "")
                                filename = os.path.basename(file_path) or "presentation.pptx"
                                await on_ppt_created(filename)
                        except (json.JSONDecodeError, TypeError) as e:
                            # 结果解析失败不致命（文件已落盘），仅记录
                            logger.warning(
                                "[LangChain Agent/流式] generate_ppt 结果解析失败: %s", e
                            )
        except Exception as e:
            logger.error("[LangChain Agent/流式] 执行异常: %s", e)
            yield make_event(ERROR, {"message": f"执行异常: {e}"})
        finally:
            # 4. 保存记忆（失败不影响已推送的事件）
            response_text = "".join(response_parts)
            if response_text:
                try:
                    await self.memory.save(session_id, user_message, response_text)
                except Exception as e:
                    logger.error("[LangChain Agent/流式] 保存记忆失败: %s", e)
            logger.info(
                "[LangChain Agent/流式] 会话 %s 完成, 耗时 %.2fs",
                session_id, time.time() - start,
            )
            yield make_event(
                DONE,
                {
                    "session_id": session_id,
                    "elapsed_seconds": round(time.time() - start, 2),
                },
            )

    async def run_stream(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        trace_meta: Optional[dict] = None,
    ) -> AsyncIterator[dict]:
        """对话流式响应"""
        async for event in self._stream_core(user_message, session_id):
            yield event

    async def run_ppt_stream(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        on_ppt_created: Optional[Callable[[str], Awaitable[None]]] = None,
        trace_meta: Optional[dict] = None,
    ) -> AsyncIterator[dict]:
        """PPT 创作流式（供 ppt 控制器调用）。

        generate_ppt 成功时触发 on_ppt_created 回调，
        由控制器完成配额扣减与创作记录。
        """
        async for event in self._stream_core(
            user_message, session_id, on_ppt_created=on_ppt_created
        ):
            yield event

    async def clear_history(self, session_id: str):
        """清除会话历史"""
        await self.memory.clear(session_id)
        logger.info("[LangChain Agent] 会话 %s 历史已清除", session_id)
