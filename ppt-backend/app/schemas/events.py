"""SSE 流式响应事件定义"""

# 状态提示（"正在分析需求..."）
AGENT_THINKING = "AGENT_THINKING"

# 任务分类完成 {type: "simple" | "complex"}
TASK_CLASSIFIED = "TASK_CLASSIFIED"

# 计划创建完成 {steps: [...], total: N}
PLAN_CREATED = "PLAN_CREATED"

# 开始执行某个计划步骤 {step, total, description}
PLAN_STEP_START = "PLAN_STEP_START"

# 计划步骤完成 {step, status: "done" | "error", error?}
PLAN_STEP_END = "PLAN_STEP_END"

# 即将调用工具 {tool, args}
TOOL_CALL = "TOOL_CALL"

# 工具执行结果 {tool, result}
TOOL_RESULT = "TOOL_RESULT"

# 流式文本片段 {content}
TEXT_DELTA = "TEXT_DELTA"

# 错误 {message}
ERROR = "ERROR"

# 流结束 {session_id, elapsed_seconds}
DONE = "DONE"

# 多智能体：当前专家切换 {agent: "supervisor"|"content"|"image"|"chart"|"beautify"}
# （多智能体增强事件，前端可忽略，向前兼容）
AGENT_SWITCH = "AGENT_SWITCH"

# 大纲人工审阅：大纲已生成并暂停，等待用户编辑 {outline, thread_id}
# （仅 OUTLINE_REVIEW_ENABLED 开启时由第一段 SSE 推送；前端据此弹编辑器）
OUTLINE_REVIEW = "OUTLINE_REVIEW"


def make_event(event_type: str, data: dict | None = None) -> dict:
    """构造一个 SSE 事件字典

    Args:
        event_type: 事件类型常量
        data: 事件数据（默认空字典）

    Returns:
        {"event": event_type, "data": data}
        （控制器序列化时把 event 作为 payload 的 "type" 字段）
    """
    return {"event": event_type, "data": data or {}}
