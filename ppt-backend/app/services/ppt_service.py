"""PPT 创作服务：配额检查 + 原子扣减 + 创作记录 + 断点恢复状态记账"""

from typing import Optional

from databases import Database

from app.core.exceptions import ErrorCode, throw_if


# 断点恢复阶段常量（与 sys_ppt.stage 列取值一致）
STAGE_CREATED = "CREATED"
STAGE_OUTLINE_DONE = "OUTLINE_DONE"
STAGE_RESEARCH_DONE = "RESEARCH_DONE"
STAGE_CONTENT_DONE = "CONTENT_DONE"
STAGE_BEAUTIFY_DONE = "BEAUTIFY_DONE"

# 终态阶段集合（达到后不再允许 stage 转换 / 不再扣配额）
TERMINAL_STAGES = (STAGE_CONTENT_DONE, STAGE_BEAUTIFY_DONE)

# specialist role → 落库字段名（与 sys_ppt 列名一致）
ROLE_TO_FIELD = {"outline": "outline", "research": "research", "content": "filename"}
# specialist role → 完成时推进到的 stage
ROLE_TO_STAGE = {
    "outline": STAGE_OUTLINE_DONE,
    "research": STAGE_RESEARCH_DONE,
    "content": STAGE_CONTENT_DONE,
}

# update_progress 允许更新的字段白名单（防 SQL 注入）
_PROGRESS_FIELDS = {"outline", "research", "filename", "stage", "errorMessage"}


class PptService:
    """PPT 创作服务"""

    def __init__(self, db: Database):
        self.db = db

    # ============================================================
    # 配额
    # ============================================================
    async def get_quota(self, user_id: int) -> int:
        """查询用户剩余配额（用户不存在返回 0）"""
        row = await self.db.fetch_one(
            query="SELECT ppt_quota FROM sys_user WHERE id = :id AND status = 1",
            values={"id": user_id},
        )
        return row["ppt_quota"] if row else 0

    async def check_quota(self, user_id: int) -> None:
        """生成前门控：配额不足抛 QUOTA_NOT_ENOUGH。

        必须在 SSE 流开启前同步调用（流中途不能抛业务异常）。
        """
        quota = await self.get_quota(user_id)
        throw_if(quota <= 0, ErrorCode.QUOTA_NOT_ENOUGH, f"PPT 配额不足，剩余 {quota} 次")

    async def deduct_and_record(
        self, user_id: int, filename: str, topic: str, style: str
    ) -> tuple:
        """原子扣减配额并写入创作记录。

        Returns:
            (是否扣减成功, 扣减后剩余配额)
        """
        async with self.db.transaction():
            # 原子扣减：仅当还有配额时成功，rowcount==0 表示并发竞态被抢空
            rowcount = await self.db.execute(
                query="UPDATE sys_user SET ppt_quota = ppt_quota - 1 WHERE id = :id AND ppt_quota > 0",
                values={"id": user_id},
            )
            if not rowcount:
                return False, await self.get_quota(user_id)

            await self.db.execute(
                query=(
                    "INSERT INTO sys_ppt (userId, filename, topic, style, status, stage, createTime, updateTime) "
                    "VALUES (:uid, :filename, :topic, :style, 'SUCCESS', 'CREATED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                values={
                    "uid": user_id,
                    "filename": filename,
                    "topic": topic,
                    "style": style,
                },
            )
            return True, await self.get_quota(user_id)

    # ============================================================
    # 断点恢复：任务全生命周期记账
    # ============================================================
    async def create_task(
        self, user_id: int, topic: str, style: str, session_id: Optional[str]
    ) -> int:
        """创建创作任务（status=IN_PROGRESS, stage=CREATED）。返回新 ppt_id。"""
        return await self.db.execute(
            query=(
                "INSERT INTO sys_ppt (userId, topic, style, status, stage, sessionId, createTime, updateTime) "
                "VALUES (:uid, :topic, :style, 'IN_PROGRESS', 'CREATED', :sid, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            values={"uid": user_id, "topic": topic, "style": style, "sid": session_id},
        )

    async def update_progress(self, ppt_id: int, **fields) -> None:
        """白名单增量更新任务进度（outline/research/filename/stage/errorMessage）。

        仅更新提供的非 None 键。进度落库失败不应致命，调用方应 try/except。
        """
        updates = {k: v for k, v in fields.items() if k in _PROGRESS_FIELDS and v is not None}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        await self.db.execute(
            query=f"UPDATE sys_ppt SET {set_clause}, updateTime = CURRENT_TIMESTAMP WHERE id = :pid",
            values={**updates, "pid": ppt_id},
        )

    async def deduct_for_task(
        self, ppt_id: int, user_id: int, filename: str
    ) -> tuple[bool, int]:
        """content 成功后：原子扣配额 + 标记 CONTENT_DONE。

        乐观锁：仅当 stage 还未到终态时才扣，rowcount==0 表示并发请求已扣过 → 幂等不重复扣。

        Returns:
            (是否由本次调用扣减, 扣减后剩余配额)
        """
        async with self.db.transaction():
            # 1) 乐观锁抢占 stage 转换；rowcount==0 表示已被并发扣过
            rc = await self.db.execute(
                query=(
                    "UPDATE sys_ppt SET filename = :filename, stage = 'CONTENT_DONE', updateTime = CURRENT_TIMESTAMP "
                    "WHERE id = :pid AND status = 'IN_PROGRESS' "
                    "AND stage NOT IN ('CONTENT_DONE', 'BEAUTIFY_DONE')"
                ),
                values={"filename": filename, "pid": ppt_id},
            )
            if not rc:
                return False, await self.get_quota(user_id)
            # 2) 扣配额（ppt_quota>0 兜底，极端并发被抢空时返回 False）
            rowcount = await self.db.execute(
                query="UPDATE sys_user SET ppt_quota = ppt_quota - 1 WHERE id = :id AND ppt_quota > 0",
                values={"id": user_id},
            )
            if not rowcount:
                # 抛出异常让事务同时回滚任务状态，不能留下未扣配额的 CONTENT_DONE。
                throw_if(True, ErrorCode.QUOTA_NOT_ENOUGH, "PPT 配额已用尽")
            return True, await self.get_quota(user_id)

    async def mark_success(self, ppt_id: int) -> None:
        """流正常结束且已生成文件 → 标记成功。"""
        await self.db.execute(
            query=(
                "UPDATE sys_ppt SET status = 'SUCCESS', stage = 'BEAUTIFY_DONE', updateTime = CURRENT_TIMESTAMP "
                "WHERE id = :pid"
            ),
            values={"pid": ppt_id},
        )

    async def mark_failed(self, ppt_id: int, error: Optional[str]) -> None:
        """流异常结束 → 标记失败并记录原因。"""
        await self.db.execute(
            query=(
                "UPDATE sys_ppt SET status = 'FAILED', errorMessage = :err, updateTime = CURRENT_TIMESTAMP "
                "WHERE id = :pid"
            ),
            values={"pid": ppt_id, "err": (error or "")[:500]},
        )

    async def get_task(self, ppt_id: int, user_id: int) -> Optional[dict]:
        """单条任务查询（带 userId 越权防护）。返回全字段 dict 或 None。"""
        row = await self.db.fetch_one(
            query=(
                "SELECT id, userId, filename, topic, style, status, stage, "
                "outline, research, sessionId, createTime, updateTime, errorMessage "
                "FROM sys_ppt WHERE id = :pid AND userId = :uid"
            ),
            values={"pid": ppt_id, "uid": user_id},
        )
        return self._shape(row)

    async def list_by_user(
        self,
        user_id: int,
        current: int,
        page_size: int,
        status: Optional[str] = None,
    ) -> dict:
        """分页查询用户任务（镜像 UserService.list_users_quota 形状）。"""
        where = "userId = :uid"
        values: dict = {"uid": user_id}
        if status:
            where += " AND status = :status"
            values["status"] = status

        total = await self.db.fetch_val(
            query=f"SELECT COUNT(id) FROM sys_ppt WHERE {where}",
            values=values,
        )

        offset = (current - 1) * page_size
        rows = await self.db.fetch_all(
            query=(
                "SELECT id, filename, topic, style, status, stage, createTime, updateTime "
                f"FROM sys_ppt WHERE {where} "
                "ORDER BY id DESC LIMIT :limit OFFSET :offset"
            ),
            values={**values, "limit": page_size, "offset": offset},
        )

        records = [
            {
                "id": r["id"],
                "filename": r["filename"],
                "topic": (
                    (r["topic"][:80] + "...") if r["topic"] and len(r["topic"]) > 80 else r["topic"]
                ),
                "style": r["style"],
                "status": r["status"],
                "stage": r["stage"],
                "createTime": r["createTime"].isoformat() if r["createTime"] else None,
                "updateTime": r["updateTime"].isoformat() if r["updateTime"] else None,
            }
            for r in rows
        ]
        return {
            "records": records,
            "total": total,
            "current": current,
            "pageSize": page_size,
        }

    @staticmethod
    def _shape(row) -> Optional[dict]:
        """行 → dict（含 outline/research 等全字段，时间 isoformat）。"""
        if not row:
            return None
        return {
            "id": row["id"],
            "userId": row["userId"],
            "filename": row["filename"],
            "topic": row["topic"],
            "style": row["style"],
            "status": row["status"],
            "stage": row["stage"],
            "outline": row["outline"],
            "research": row["research"],
            "sessionId": row["sessionId"],
            "createTime": row["createTime"].isoformat() if row["createTime"] else None,
            "updateTime": row["updateTime"].isoformat() if row["updateTime"] else None,
            "errorMessage": row["errorMessage"],
        }
