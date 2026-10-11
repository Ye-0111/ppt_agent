"""任务分类与计划创建器 - 使用 LangChain 结构化输出

集成两种结构化输出方式：
- classify(): 使用 Pydantic BaseModel (TaskClassification) 自动验证
- create_plan(): 使用 TypedDict (ExecutionPlan) 轻量解析
"""

import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.agent.prompts import CLASSIFY_PROMPT, PLAN_PROMPT
from app.core.config import settings
from app.schemas.structured_output import TaskClassification, ExecutionPlan

logger = logging.getLogger(__name__)

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class Planner:
    """任务分类与计划创建器（使用 with_structured_output，无需手动解析 JSON）"""

    def __init__(self):
        base_llm = ChatOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=DASHSCOPE_BASE_URL,
            model=settings.dashscope_model,
            temperature=0.0,
        )

        # Pydantic BaseModel — 用于任务分类
        self.classify_llm = base_llm.with_structured_output(
            TaskClassification, method="json_mode"
        )

        # TypedDict — 用于计划创建
        self.plan_llm = base_llm.with_structured_output(
            ExecutionPlan, method="json_mode"
        )

    async def classify(self, user_message: str, history_summary: str = "") -> bool:
        """判断任务是否为复杂任务。

        使用 Pydantic BaseModel 结构化输出，无需手动解析 JSON。
        直接获得 TaskClassification 实例，自动验证类型和字段。

        Returns:
            True 表示复杂任务（需要规划），False 表示简单任务
        """
        prompt = CLASSIFY_PROMPT.format(user_message=user_message)
        if history_summary:
            prompt += f"\n\n对话历史摘要：{history_summary}"

        try:
            result: TaskClassification = await self.classify_llm.ainvoke(
                [HumanMessage(content=prompt)]
            )
            logger.info(
                "任务分类: 复杂=%s, 理由: %s, 建议工具: %s",
                result.is_complex, result.reason, result.suggested_tools,
            )
            return result.is_complex

        except Exception as e:
            logger.warning("任务分类失败，默认简单任务: %s", e)
            return False

    async def create_plan(
        self, user_message: str, history_summary: str = ""
    ) -> list[dict]:
        """为复杂任务创建执行计划。

        使用 TypedDict 结构化输出，返回普通 dict。
        无需手动 _parse_json 提取逻辑。

        Returns:
            步骤列表 [{"description": "...", "expected_tools": [...]}, ...]
        """
        max_steps = getattr(settings, "agent_max_plan_steps", 8)
        prompt = PLAN_PROMPT.format(user_message=user_message, max_steps=max_steps)
        if history_summary:
            prompt += f"\n\n对话历史摘要：{history_summary}"

        try:
            result = await self.plan_llm.ainvoke(
                [HumanMessage(content=prompt)]
            )

            raw_steps = result if isinstance(result, list) else result.get("steps", [])

            steps = [
                {
                    "description": step.get("description", f"步骤 {i + 1}"),
                    "expected_tools": step.get("expected_tools", []),
                }
                for i, step in enumerate(raw_steps)
                if isinstance(step, dict)
            ]

            if steps:
                logger.info(
                    "计划创建成功: %d 步 - %s",
                    len(steps),
                    " → ".join(s["description"][:20] for s in steps),
                )
                return steps

        except Exception as e:
            logger.warning("计划创建失败，降级为单步: %s", e)

        # 降级：单步计划
        return [{"description": f"完成用户请求: {user_message}", "expected_tools": []}]
