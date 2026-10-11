"""会话记忆组件 - SummaryBufferMemory（混合摘要记忆）"""

import json
import logging
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from app.core import redis as redis_module

logger = logging.getLogger(__name__)

# Redis key 前缀
_HISTORY_PREFIX = "chat:history:"     # 近期完整对话
_SUMMARY_PREFIX = "chat:summary:"    # 远期对话摘要

# 摘要提示词
_SUMMARY_PROMPT = """请逐步分析以下对话记录，用一段简洁的中文摘要概括其中的关键信息。
重点保留：用户的个人信息、偏好、核心需求、已确定的结论等重要上下文。
忽略：寒暄、重复提问、无关紧要的细节。

对话记录：
{conversation}

请直接输出摘要内容，不要加前缀说明："""


class SummaryBufferMemory:
    """混合摘要记忆组件"""

    def __init__(
        self,
        summary_llm: BaseChatModel,
        buffer_rounds: int = 5,
        summary_trigger: int = 7,
    ):
        self.summary_llm = summary_llm
        self.buffer_rounds = buffer_rounds
        self.summary_trigger = summary_trigger

    async def load(self, session_id: str) -> list:
        """加载对话历史（远期摘要 + 近期原文"""
        if not redis_module.redis_client:
            return []

        messages = []

        # 1. 远期摘要 → SystemMessage
        summary = await redis_module.redis_client.get(f"{_SUMMARY_PREFIX}{session_id}")
        if summary:
            messages.append(SystemMessage(content=f"[对话历史摘要]\n{summary}"))

        # 2. 近期完整对话 → HumanMessage / AIMessage
        raw = await redis_module.redis_client.get(f"{_HISTORY_PREFIX}{session_id}")
        if raw:
            for record in json.loads(raw):
                if record["role"] == "human":
                    messages.append(HumanMessage(content=record["content"]))
                elif record["role"] == "ai":
                    messages.append(AIMessage(content=record["content"]))

        return messages

    async def save(self, session_id: str, user_msg: str, ai_msg: str):
        """保存一轮对话，超出阈值时自动摘要化早期部分"""
        if not redis_module.redis_client:
            return

        history_key = f"{_HISTORY_PREFIX}{session_id}"
        summary_key = f"{_SUMMARY_PREFIX}{session_id}"

        # 1. 读取现有近期对话，追加本轮
        raw = await redis_module.redis_client.get(history_key)
        records: list[dict] = json.loads(raw) if raw else []
        records.append({"role": "human", "content": user_msg})
        records.append({"role": "ai", "content": ai_msg})

        # 2. 判断是否触发摘要
        total_rounds = len(records) // 2
        if total_rounds > self.summary_trigger:
            rounds_to_summarize = total_rounds - self.buffer_rounds
            cut_index = rounds_to_summarize * 2

            old_records = records[:cut_index]
            records = records[cut_index:]

            await self._summarize(summary_key, old_records)

        # 3. 写回 Redis
        await redis_module.redis_client.set(
            history_key,
            json.dumps(records, ensure_ascii=False),
        )
        # 摘要 key 保持与 history key 相同的存活状态（不过期）

    async def clear(self, session_id: str):
        """清除指定会话的全部历史（摘要 + 近期对话）"""
        if not redis_module.redis_client:
            return
        await redis_module.redis_client.delete(
            f"{_HISTORY_PREFIX}{session_id}",
            f"{_SUMMARY_PREFIX}{session_id}",
        )

    async def _summarize(self, summary_key: str, old_records: list[dict]):
        """调用 LLM 将早期对话压缩为摘要（追加模式）"""
        existing = await redis_module.redis_client.get(summary_key) or ""

        parts: list[str] = []
        if existing:
            parts.append(f"[已有历史摘要]\n{existing}\n\n[新增长对话]")
        for r in old_records:
            role = "用户" if r["role"] == "human" else "AI"
            parts.append(f"{role}: {r['content']}")
        conversation_text = "\n".join(parts)

        response = await self.summary_llm.ainvoke(
            [HumanMessage(content=_SUMMARY_PROMPT.format(conversation=conversation_text))]
        )

        await redis_module.redis_client.set(summary_key, response.content)
