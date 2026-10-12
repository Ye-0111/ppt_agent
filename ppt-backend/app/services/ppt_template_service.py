"""PPT 模板服务 - sys_ppt_template 的 CRUD（databases.Database 异步 raw SQL）。"""

import json
import logging
from pathlib import Path
from typing import Optional

from databases import Database

from app.core.config import settings

logger = logging.getLogger(__name__)


class PptTemplateService:
    """PPT 模板库服务（仅存已含 {{占位符}} 的成品模板）。"""

    def __init__(self, db: Database):
        self.db = db

    async def create(
        self,
        user_id: int,
        name: str,
        filename: str,
        variables_json: Optional[str],
        slide_count: Optional[int],
        is_public: int,
    ) -> int:
        """新增模板，返回新 id。"""
        return await self.db.execute(
            query=(
                "INSERT INTO sys_ppt_template "
                "(userId, name, filename, variables, slideCount, isPublic, createTime, updateTime) "
                "VALUES (:uid, :name, :filename, :variables, :slideCount, :isPublic, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            values={
                "uid": user_id,
                "name": name,
                "filename": filename,
                "variables": variables_json,
                "slideCount": slide_count,
                "isPublic": is_public,
            },
        )

    async def get(self, template_id: int, user_id: int) -> Optional[dict]:
        """单条查询：自己上传或公开可见。返回 dict 或 None。"""
        row = await self.db.fetch_one(
            query=(
                "SELECT id, userId, name, filename, variables, slideCount, isPublic, "
                "createTime, updateTime FROM sys_ppt_template "
                "WHERE id = :id AND (userId = :uid OR isPublic = 1)"
            ),
            values={"id": template_id, "uid": user_id},
        )
        return self._shape(row)

    async def get_owned(self, template_id: int, user_id: int) -> Optional[dict]:
        """严格 owner 匹配（删除 / 用模板创作时鉴权用）。"""
        row = await self.db.fetch_one(
            query=(
                "SELECT id, userId, name, filename, variables, slideCount, isPublic, "
                "createTime, updateTime FROM sys_ppt_template "
                "WHERE id = :id AND userId = :uid"
            ),
            values={"id": template_id, "uid": user_id},
        )
        return self._shape(row)

    async def list_templates(
        self,
        user_id: int,
        current: int,
        page_size: int,
        scope: str = "all",
    ) -> dict:
        """分页查询。scope: mine / public / all（all = 自己 + 公开）。"""
        if scope == "mine":
            where, values = "userId = :uid", {"uid": user_id}
        elif scope == "public":
            where, values = "isPublic = 1", {}
        else:  # all
            where, values = "userId = :uid OR isPublic = 1", {"uid": user_id}

        total = await self.db.fetch_val(
            query=f"SELECT COUNT(id) FROM sys_ppt_template WHERE {where}",
            values=values,
        )

        offset = (current - 1) * page_size
        rows = await self.db.fetch_all(
            query=(
                "SELECT id, userId, name, filename, variables, slideCount, isPublic, "
                "createTime, updateTime FROM sys_ppt_template "
                f"WHERE {where} "
                "ORDER BY id DESC LIMIT :limit OFFSET :offset"
            ),
            values={**values, "limit": page_size, "offset": offset},
        )
        records = [self._shape(r) for r in rows]
        return {
            "records": records,
            "total": total,
            "current": current,
            "pageSize": page_size,
        }

    async def delete(self, template_id: int, user_id: int) -> bool:
        """删除模板（仅 owner）。同时 best-effort 删除 ppt_templates/ 下的文件。"""
        owned = await self.get_owned(template_id, user_id)
        if not owned:
            return False
        rowcount = await self.db.execute(
            query="DELETE FROM sys_ppt_template WHERE id = :id AND userId = :uid",
            values={"id": template_id, "uid": user_id},
        )
        if not rowcount:
            return False
        # best-effort 清理文件
        try:
            path = settings.workspace_path / "ppt_templates" / owned["filename"]
            if path.is_file():
                path.unlink()
        except Exception as e:
            logger.warning("删除模板文件失败 id=%s: %s", template_id, e)
        return True

    @staticmethod
    def _shape(row) -> Optional[dict]:
        """行 → camelCase dict；variables 反序列化为数组。"""
        if not row:
            return None
        variables_raw = row["variables"]
        try:
            variables = json.loads(variables_raw) if variables_raw else []
        except (json.JSONDecodeError, TypeError):
            variables = []
        return {
            "id": row["id"],
            "userId": row["userId"],
            "name": row["name"],
            "filename": row["filename"],
            "variables": variables,
            "slideCount": row["slideCount"],
            "isPublic": bool(row["isPublic"]),
            "createTime": row["createTime"].isoformat() if row["createTime"] else None,
            "updateTime": row["updateTime"].isoformat() if row["updateTime"] else None,
        }
