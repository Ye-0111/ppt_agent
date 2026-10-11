"""智能体执行日志服务（参考 backend agent_log_service.py）。

⚠️ 关键差异（写库方式）：backend 用 ``asyncio.create_task`` 后台写；test 用 **inline await**。
ASGI streaming generator 里 detached task 会被拆除丢写/乱序/吞异常（见 CLAUDE.md 断点恢复坑，
``on_stage`` 落库即 inline await 先例）。故 ``save_log`` 为 inline await，
``agent_log_context`` 在 finally 里 inline await 写库。
"""

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from databases import Database

from app.core.database import database
from app.schemas.agent_log import AgentExecutionStatsVO, AgentLogVO

logger = logging.getLogger(__name__)


class AgentLogService:
    """智能体执行日志服务。"""

    def __init__(self, db: Database):
        self.db = db

    async def save_log(self, log_data: Dict[str, Any]) -> None:
        """写入一条日志记录（inline await）。调用方（agent_log_context）负责 try/except。"""
        await self.db.execute(
            query="""
                INSERT INTO sys_agent_log (
                    taskId, agentName, startTime, endTime, durationMs, status,
                    errorMessage, prompt, inputData, outputData
                ) VALUES (
                    :taskId, :agentName, :startTime, :endTime, :durationMs, :status,
                    :errorMessage, :prompt, :inputData, :outputData
                )
            """,
            values={
                "taskId": log_data.get("taskId"),
                "agentName": log_data.get("agentName"),
                "startTime": log_data.get("startTime"),
                "endTime": log_data.get("endTime"),
                "durationMs": log_data.get("durationMs"),
                "status": log_data.get("status"),
                "errorMessage": log_data.get("errorMessage"),
                "prompt": log_data.get("prompt"),
                "inputData": log_data.get("inputData"),
                "outputData": log_data.get("outputData"),
            },
        )
        logger.info(
            "智能体日志已保存, taskId=%s, agentName=%s, status=%s, durationMs=%s",
            log_data.get("taskId"),
            log_data.get("agentName"),
            log_data.get("status"),
            log_data.get("durationMs"),
        )

    async def get_logs_by_task_id(self, task_id: str) -> List[AgentLogVO]:
        """查询任务下的全部执行日志（按创建时间升序）。"""
        rows = await self.db.fetch_all(
            query="""
                SELECT id, taskId, agentName, startTime, endTime, durationMs, status,
                       errorMessage, prompt, inputData, outputData, createTime, updateTime
                FROM sys_agent_log
                WHERE taskId = :taskId AND isDelete = 0
                ORDER BY createTime ASC
            """,
            values={"taskId": task_id},
        )
        return [self._to_agent_log_vo(dict(row)) for row in rows]

    async def get_execution_stats(self, task_id: str) -> AgentExecutionStatsVO:
        """获取任务执行统计：总耗时、各 specialist 耗时、整体状态。"""
        logs = await self.get_logs_by_task_id(task_id)
        if not logs:
            return AgentExecutionStatsVO(
                taskId=task_id,
                totalDurationMs=0,
                agentCount=0,
                agentDurations={},
                overallStatus="NOT_FOUND",
                logs=[],
            )

        total_duration_ms = 0
        agent_durations: Dict[str, int] = {}
        overall_status = "SUCCESS"

        for log_item in logs:
            if log_item.duration_ms is not None:
                total_duration_ms += log_item.duration_ms
                agent_durations[log_item.agent_name] = log_item.duration_ms
            if log_item.status == "FAILED":
                overall_status = "FAILED"
            elif log_item.status == "RUNNING" and overall_status != "FAILED":
                overall_status = "RUNNING"

        return AgentExecutionStatsVO(
            taskId=task_id,
            totalDurationMs=total_duration_ms,
            agentCount=len(logs),
            agentDurations=agent_durations,
            overallStatus=overall_status,
            logs=logs,
        )

    def _to_agent_log_vo(self, row: Dict[str, Any]) -> AgentLogVO:
        """数据库行 → AgentLogVO。"""
        return AgentLogVO(
            id=row["id"],
            taskId=row["taskId"],
            agentName=row["agentName"],
            startTime=self._to_iso(row.get("startTime")),
            endTime=self._to_iso(row.get("endTime")),
            durationMs=row.get("durationMs"),
            status=row["status"],
            errorMessage=row.get("errorMessage"),
            prompt=row.get("prompt"),
            inputData=row.get("inputData"),
            outputData=row.get("outputData"),
            createTime=self._to_iso(row.get("createTime")),
            updateTime=self._to_iso(row.get("updateTime")),
        )

    @staticmethod
    def _to_iso(value: Optional[datetime]) -> Optional[str]:
        if value is None:
            return None
        return value.isoformat()


@asynccontextmanager
async def agent_log_context(
    task_id: Optional[str],
    agent_name: str,
    prompt: Optional[str] = None,
    input_data: Optional[dict] = None,
):
    """specialist 节点执行日志上下文。

    - 进入：记 startTime + status=RUNNING + prompt + inputData(JSON)。
    - 块内：调用方可向 ``log_data["outputData"]`` 填产出摘要。
    - 正常退出 → status=SUCCESS；异常 → status=FAILED + errorMessage 并 ``raise``（不吞业务异常）。
    - finally：算 durationMs，**inline await** 写库（非 create_task，避 ASGI detached task 坑）；
      写库失败仅 warning，不阻断主链路。

    ``task_id`` 为 None 时记 ``"unknown"``（对话路径不走 specialist，正常都有 ppt_id）。
    """
    start_time = datetime.now()
    log_data: Dict[str, Any] = {
        "taskId": task_id or "unknown",
        "agentName": agent_name,
        "startTime": start_time,
        "status": "RUNNING",
        "prompt": prompt,
        "inputData": _safe_json_dumps(input_data),
        "outputData": None,
        "errorMessage": None,
    }
    try:
        yield log_data
        log_data["status"] = "SUCCESS"
    except Exception as exc:
        log_data["status"] = "FAILED"
        log_data["errorMessage"] = str(exc)
        raise
    finally:
        end_time = datetime.now()
        log_data["endTime"] = end_time
        log_data["durationMs"] = int((end_time - start_time).total_seconds() * 1000)
        try:
            await AgentLogService(database).save_log(log_data)
        except Exception as e:
            logger.warning(
                "[agent_log] 写入失败 taskId=%s agentName=%s: %s",
                log_data.get("taskId"),
                log_data.get("agentName"),
                e,
            )


def _safe_json_dumps(value: Optional[dict]) -> Optional[str]:
    """安全序列化 JSON（容错不可序列化对象）。"""
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)
