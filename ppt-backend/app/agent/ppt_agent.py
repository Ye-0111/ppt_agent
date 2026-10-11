"""PPT 创作智能体 - 基于 ReAct + Plan-Execute 的单智能体架构

架构说明：
- Plan-Execute 是外层循环：任务分类 → 创建计划 → 逐步执行 → 审查结果
- ReAct 是内层循环：Think（推理）→ Act（工具调用）→ Observe（观察结果）
- 单智能体，不多 agent
"""

import logging
import time
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.core.config import settings
from app.tools import all_tools
from app.utils.memory import SummaryBufferMemory
from app.agent.prompts import SYSTEM_PROMPT, REVIEW_PROMPT
from app.agent.planner import Planner

logger = logging.getLogger(__name__)

# DashScope 兼容 OpenAI 的 API 地址
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

DEFAULT_MAX_REACT_ITERATIONS = 10


class PPTAgent:
    """PPT 创作智能体（ReAct + Plan-Execute）"""

    def __init__(self):
        # 1. 主 LLM（带工具绑定）
        self.llm = ChatOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=DASHSCOPE_BASE_URL,
            model=settings.dashscope_model,
            temperature=0.7,
        )

        # 2. 摘要 LLM（低 temperature，用于记忆摘要）
        summary_llm = ChatOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=DASHSCOPE_BASE_URL,
            model=settings.dashscope_model,
            temperature=0.0,
        )

        # 3. 工具
        self.tools = all_tools
        self.tool_map = {t.name: t for t in self.tools}
        self.llm_with_tools = self.llm.bind_tools(self.tools)

        # 4. 组件
        self.memory = SummaryBufferMemory(summary_llm=summary_llm)
        self.planner = Planner()

        # 5. 配置
        self.max_react_iterations = getattr(
            settings, "agent_max_react_iterations", DEFAULT_MAX_REACT_ITERATIONS
        )
        self.enable_review = getattr(settings, "agent_enable_plan_review", True)

    # ================================================================
    # 主入口
    # ================================================================

    async def run(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        trace_meta: Optional[dict] = None,
    ) -> str:
        """智能体主入口 — Plan-Execute + ReAct

        Returns:
            回复文本
        """
        session_id = session_id or "default"
        start = time.time()

        logger.info("[智能体] 会话 %s 收到消息: %s", session_id, user_message[:100])

        # 1. 加载记忆
        history = await self.memory.load(session_id)

        # 2. 任务分类
        history_summary = self._extract_summary(history)
        is_complex = await self.planner.classify(user_message, history_summary)

        if not is_complex:
            # ── 简单任务：直接回复 ──
            logger.info("[智能体] 简单任务，直接回复")
            response_text = await self._direct_response(user_message, history)
        else:
            # ── 复杂任务：Plan-Execute + ReAct ──
            logger.info("[智能体] 复杂任务，启动 Plan-Execute")

            # 3. 创建计划
            plan_steps = await self.planner.create_plan(user_message, history_summary)
            logger.info("[智能体] 计划: %d 步", len(plan_steps))

            # 4. 逐步执行（每步 ReAct）
            messages = self._build_messages(user_message, history)

            for idx, step in enumerate(plan_steps):
                # 注入步骤上下文
                step_context = (
                    f"[计划执行] 当前步骤 {idx + 1}/{len(plan_steps)}\n"
                    f"步骤描述: {step['description']}\n"
                    f"预期使用的工具: {', '.join(step.get('expected_tools', [])) or '自动判断'}\n"
                    f"请执行此步骤。"
                )
                messages.append(SystemMessage(content=step_context))

                logger.info(
                    "[智能体] 步骤 %d/%d: %s",
                    idx + 1, len(plan_steps), step["description"][:50],
                )

                try:
                    await self._react_loop(messages)
                except Exception as e:
                    logger.error("[智能体] 步骤 %d 执行失败: %s", idx + 1, e)

            # 5. 审查结果
            if self.enable_review:
                response_text = await self._review_results(messages, plan_steps, user_message)
            else:
                response_text = messages[-1].content if messages else "任务执行完成。"

        # 6. 保存记忆
        await self.memory.save(session_id, user_message, response_text)

        logger.info(
            "[智能体] 会话 %s 完成, 耗时 %.2fs",
            session_id, time.time() - start,
        )
        return response_text

    # ================================================================
    # ReAct 循环
    # ================================================================

    async def _react_loop(self, messages: list) -> str:
        """ReAct 循环：Think → Act → Observe

        Args:
            messages: 消息列表（原地修改）

        Returns:
            最终回复文本
        """
        for iteration in range(self.max_react_iterations):
            # THINK
            response = await self.llm_with_tools.ainvoke(messages)

            # 无工具调用 → 最终回复
            if not response.tool_calls:
                logger.debug("[ReAct] 迭代 %d: 最终回复", iteration + 1)
                return response.content or ""

            # ACT：执行工具
            messages.append(response)
            for tool_call in response.tool_calls:
                logger.info(
                    "[ReAct] 迭代 %d: 调用 %s(%s)",
                    iteration + 1, tool_call["name"],
                    str(tool_call["args"])[:100],
                )
                observation = await self._execute_tool(
                    tool_call["name"], tool_call["args"]
                )
                # OBSERVE
                messages.append(ToolMessage(
                    content=observation,
                    tool_call_id=tool_call["id"],
                ))

        logger.warning("[ReAct] 达到最大迭代 %d", self.max_react_iterations)
        return "达到最大推理迭代次数，已部分完成。如需继续请告诉我。"

    # ================================================================
    # 简单任务
    # ================================================================

    async def _direct_response(self, user_message: str, history: list) -> str:
        """简单任务：直接对话（允许一轮工具调用）"""
        messages = self._build_messages(user_message, history)
        response = await self.llm_with_tools.ainvoke(messages)

        if response.tool_calls:
            messages.append(response)
            for tc in response.tool_calls:
                result = await self._execute_tool(tc["name"], tc["args"])
                messages.append(ToolMessage(
                    content=result, tool_call_id=tc["id"],
                ))
            response = await self.llm_with_tools.ainvoke(messages)

        return response.content

    # ================================================================
    # 工具执行
    # ================================================================

    async def _execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """执行单个工具"""
        tool = self.tool_map.get(tool_name)
        if not tool:
            return f"错误：未知工具 '{tool_name}'"
        try:
            result = await tool.ainvoke(tool_args)
            return str(result) if result is not None else "工具执行完成（无返回值）"
        except Exception as e:
            logger.error("工具执行失败: %s, %s", tool_name, e)
            return f"工具执行失败: {e}"

    # ================================================================
    # 审查结果
    # ================================================================

    async def _review_results(
        self, messages: list, plan_steps: list[dict], goal: str
    ) -> str:
        """审查计划执行结果，生成最终回复"""
        lines = [f"原始目标: {goal}", f"计划步骤: {len(plan_steps)} 个", ""]
        for i, step in enumerate(plan_steps):
            lines.append(f"  ✅ 步骤 {i + 1}: {step['description']}")
        plan_summary = "\n".join(lines)

        review_text = REVIEW_PROMPT.format(plan_summary=plan_summary)
        messages.append(SystemMessage(content=review_text))

        try:
            response = await self.llm_with_tools.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.error("审查失败: %s", e)
            return messages[-1].content if messages else "任务执行完成。"

    # ================================================================
    # 辅助方法
    # ================================================================

    def _build_messages(self, user_message: str, history: list) -> list:
        """构建消息列表"""
        messages = [SystemMessage(content=SYSTEM_PROMPT)]
        messages.extend(history)
        messages.append(HumanMessage(content=user_message))
        return messages

    @staticmethod
    def _extract_summary(history: list) -> str:
        """从历史消息中提取摘要"""
        for msg in history:
            if isinstance(msg, SystemMessage) and "对话历史摘要" in msg.content:
                return msg.content
        return ""

    async def clear_history(self, session_id: str):
        """清除会话历史"""
        await self.memory.clear(session_id)
        logger.info("[智能体] 会话 %s 历史已清除", session_id)
