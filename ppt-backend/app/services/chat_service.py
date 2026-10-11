"""LangChain 大模型对话服务 - 支持工具调用"""

import json
import logging
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import ToolMessage, HumanMessage

from app.core.config import settings
from app.utils.memory import SummaryBufferMemory
from app.tools import all_tools
from app.schemas.structured_output import PPT_SLIDES_SCHEMA

logger = logging.getLogger(__name__)

# DashScope 兼容 OpenAI 的 API 地址
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 系统提示词（角色设定 + 工具使用指南）
SYSTEM_PROMPT = """你是一个 AI 助手，擅长帮助用户创作 PPT。

你可以使用以下工具来完成任务：

1. **read_file** - 读取文件内容
2. **write_file** - 写入文件
3. **list_files** - 列出目录中的文件
4. **generate_ppt** - 根据结构化 JSON 数据生成 PPTX 文件

当用户请求创建 PPT 时，请按以下流程操作：
1. 使用 generate_ppt 生成 PPTX 文件，将幻灯片数据作为 slides 参数传入
2. 告知用户文件路径和生成结果

请用简洁、专业的语气回答。"""

MAX_TOOL_ITERATIONS = 5
DEFAULT_SESSION_ID = "default"


class ChatService:
    """基于 LangChain 的对话服务（支持工具调用）"""

    def __init__(self):
        # 对话 LLM
        self.llm = ChatOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=DASHSCOPE_BASE_URL,
            model=settings.dashscope_model,
            temperature=0.7,
        )

        # 摘要 LLM（低 temperature 保证稳定）
        summary_llm = ChatOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=DASHSCOPE_BASE_URL,
            model=settings.dashscope_model,
            temperature=0.0,
        )

        # 记忆组件
        self.memory = SummaryBufferMemory(summary_llm=summary_llm)

        # 工具绑定
        self.tools = all_tools
        self.tool_map = {t.name: t for t in self.tools}
        self.llm_with_tools = self.llm.bind_tools(self.tools)

        # 提示词模板
        self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{input}"),
        ])

    async def chat(self, user_message: str, session_id: Optional[str] = None) -> str:
        """带会话记忆和工具调用的对话"""
        session_id = session_id or DEFAULT_SESSION_ID

        # 1. 读取记忆
        history = await self.memory.load(session_id)

        # 2. 构建初始消息
        messages = self.prompt_template.format_messages(
            history=history,
            input=user_message,
        )

        logger.info(
            "[会话ID: %s] 发送消息 (共 %d 条), 用户输入: %s",
            session_id, len(messages), user_message[:100],
        )

        # 3. 工具调用循环
        for iteration in range(MAX_TOOL_ITERATIONS):
            response = await self.llm_with_tools.ainvoke(messages)

            # 没有工具调用 → 最终响应
            if not response.tool_calls:
                break

            # 有工具调用 → 执行工具
            messages.append(response)
            logger.info(
                "[会话ID: %s] 第 %d 轮工具调用: %s",
                session_id, iteration + 1,
                [tc["name"] for tc in response.tool_calls],
            )

            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]

                # 执行工具
                tool_result = await self._execute_tool(tool_name, tool_args)

                messages.append(ToolMessage(
                    content=tool_result,
                    tool_call_id=tool_call["id"],
                ))

        # 4. 保存到记忆（仅保存最终的人机文本对话）
        await self.memory.save(session_id, user_message, response.content)

        return response.content

    async def generate_slides_with_schema(self, topic: str, page_count: int = 5) -> dict:
        """示例：使用 JSON Schema (PPT_SLIDES_SCHEMA) 结构化输出生成幻灯片数据

        将原来让 LLM 自由拼接 JSON 的方式，改为 with_structured_output：
            旧: response = await self.llm_with_tools.ainvoke(messages)  → 手动解析 JSON
            新: result = await self.slides_llm.ainvoke(prompt)           → 直接返回 dict

        用法：
            slides_data = await chat_service.generate_slides_with_schema("Python 入门教程", 5)
            slides_json = json.dumps(slides_data["slides"], ensure_ascii=False)
            await generate_ppt.ainvoke({"slides": slides_json, "style": slides_data["style"]})
        """
        # 创建绑定 JSON Schema 的 LLM
        slides_llm = ChatOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=DASHSCOPE_BASE_URL,
            model=settings.dashscope_model,
            temperature=0.3,
        ).with_structured_output(PPT_SLIDES_SCHEMA, method="json_mode")

        prompt = (
            f"请为以下主题设计一份 {page_count} 页的 PPT 幻灯片结构：{topic}\n"
            "要求：第一页用 title-slide 布局，其余用 content 或 two-column 布局，"
            "要点简洁（每条 15 字以内），为每页生成演讲者备注。"
        )

        result = await slides_llm.ainvoke([HumanMessage(content=prompt)])

        logger.info(
            "结构化幻灯片生成: %d 页, 风格: %s",
            len(result.get("slides", [])), result.get("style", "business"),
        )
        return result

    async def _execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """执行单个工具调用"""
        tool = self.tool_map.get(tool_name)
        if not tool:
            return f"错误：未知工具 '{tool_name}'"

        try:
            result = await tool.ainvoke(tool_args)
            return str(result) if result is not None else "工具执行完成（无返回值）"
        except Exception as e:
            logger.error("工具执行失败: %s, %s", tool_name, e)
            return f"工具执行失败: {e}"

    async def clear_history(self, session_id: str):
        """清除指定会话的历史记录"""
        await self.memory.clear(session_id)


# 模块级单例
chat_service = ChatService()
