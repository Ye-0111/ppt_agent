from datetime import datetime
import unittest
from unittest.mock import patch

from sqlite_database import SQLiteDatabase
from app.controller.ppt import _make_on_stage, _make_on_ppt_created, create_ppt, resume_ppt, resume_ppt_task
from app.core.config import settings
from app.core.exceptions import BusinessException, ErrorCode
from app.schemas.ppt import PptCreateRequest, PptOutlineResumeRequest, PptResumeRequest
from app.schemas.user import LoginUserVO
from app.services.ppt_service import PptService


class TaskLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = SQLiteDatabase()
        await self.db.execute(
            "INSERT INTO sys_user (id,username,password,ppt_quota) VALUES (1,'owner','dummy',2)"
        )
        await self.db.execute(
            "INSERT INTO sys_user (id,username,password,ppt_quota) VALUES (2,'other','dummy',2)"
        )
        self.service = PptService(self.db)
        self.pid = await self.service.create_task(1, "Test topic", "business", "u1")

    def tearDown(self):
        self.db.close()

    async def test_new_creation_checks_quota_and_creates_a_task(self):
        owner = LoginUserVO(id=1, username="owner", userRole="user", createTime="2026-10-12T00:00:00")
        with patch.object(settings, "outline_review_enabled", False):
            response = await create_ppt(PptCreateRequest(message="New test topic"), owner, self.db)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(await self.db.fetch_val("SELECT COUNT(*) FROM sys_ppt WHERE topic='New test topic'"), 1)

    async def test_content_progress_before_created_callback_still_charges_once(self):
        state = {"deducted": False, "filename": None, "remaining_quota": None}
        await _make_on_stage(self.service, self.pid, "test")("content", "test.pptx")
        # A crash here must not expose an uncharged filename to the resume route.
        interrupted_task = await self.service.get_task(self.pid, 1)
        self.assertIsNone(interrupted_task["filename"])
        callback = _make_on_ppt_created(self.service, self.pid, 1, state)
        await callback("test.pptx")
        await callback("test.pptx")
        self.assertEqual(await self.service.get_quota(1), 1)
        task = await self.service.get_task(self.pid, 1)
        self.assertEqual(task["stage"], "CONTENT_DONE")
        self.assertEqual(state["filename"], "test.pptx")

    async def test_quota_exhaustion_rolls_back_task_transition(self):
        await self.db.execute("UPDATE sys_user SET ppt_quota=0 WHERE id=1")
        with self.assertRaises(BusinessException) as error:
            await self.service.deduct_for_task(self.pid, 1, "test.pptx")
        self.assertEqual(error.exception.error_code, ErrorCode.QUOTA_NOT_ENOUGH)
        task = await self.service.get_task(self.pid, 1)
        self.assertEqual(task["stage"], "CREATED")
        self.assertIsNone(task["filename"])

    async def test_resume_of_existing_file_does_not_require_another_quota(self):
        await self.db.execute("UPDATE sys_user SET ppt_quota=0 WHERE id=1")
        await self.service.update_progress(self.pid, filename="existing.pptx", stage="CONTENT_DONE")
        owner = LoginUserVO(id=1, username="owner", userRole="user", createTime="2026-10-12T00:00:00")
        try:
            response = await resume_ppt_task(PptResumeRequest(pptId=self.pid), owner, self.db)
        except BusinessException as error:
            self.fail(f"An already generated file should resume without charging again: {error.error_code}")
        self.assertEqual(response.status_code, 200)

    async def test_resume_rejects_legacy_uncharged_file_when_quota_is_empty(self):
        await self.service.update_progress(self.pid, filename="uncharged.pptx")
        await self.db.execute("UPDATE sys_user SET ppt_quota=0 WHERE id=1")
        owner = LoginUserVO(id=1, username="owner", userRole="user", createTime="2026-10-12T00:00:00")
        with self.assertRaises(BusinessException) as error:
            await resume_ppt_task(PptResumeRequest(pptId=self.pid), owner, self.db)
        self.assertEqual(error.exception.error_code, ErrorCode.QUOTA_NOT_ENOUGH)
        task = await self.service.get_task(self.pid, 1)
        self.assertEqual(task["stage"], "CREATED")

    async def test_resume_charges_legacy_uncharged_file_once(self):
        await self.service.update_progress(self.pid, filename="uncharged.pptx")
        owner = LoginUserVO(id=1, username="owner", userRole="user", createTime="2026-10-12T00:00:00")
        for _ in range(2):
            response = await resume_ppt_task(PptResumeRequest(pptId=self.pid), owner, self.db)
            self.assertEqual(response.status_code, 200)
        self.assertEqual(await self.service.get_quota(1), 1)
        task = await self.service.get_task(self.pid, 1)
        self.assertEqual(task["stage"], "CONTENT_DONE")

    async def test_raw_progress_update_refreshes_update_time(self):
        await self.db.execute("UPDATE sys_ppt SET updateTime='2000-01-01 00:00:00' WHERE id=:id", {"id": self.pid})
        await self.service.update_progress(self.pid, outline="outline", stage="OUTLINE_DONE")
        row = await self.db.fetch_one("SELECT updateTime FROM sys_ppt WHERE id=:id", {"id": self.pid})
        self.assertGreater(row["updateTime"], datetime(2000, 1, 1))

    async def test_outline_resume_rejects_another_users_task_before_writing(self):
        request = PptOutlineResumeRequest(message="Test", outline='{"title":"Test","slides":[{"title":"One"}]}', pptId=self.pid)
        other = LoginUserVO(id=2, username="other", userRole="user", createTime="2026-10-12T00:00:00")
        with self.assertRaises(BusinessException) as error:
            await resume_ppt(request, other, self.db)
        self.assertEqual(error.exception.error_code, ErrorCode.NOT_FOUND_ERROR)
        task = await self.service.get_task(self.pid, 1)
        self.assertIsNone(task["outline"])

    async def test_outline_resume_rejects_completed_task(self):
        await self.service.mark_success(self.pid)
        request = PptOutlineResumeRequest(message="Test", outline='{"title":"Test","slides":[{"title":"One"}]}', pptId=self.pid)
        owner = LoginUserVO(id=1, username="owner", userRole="user", createTime="2026-10-12T00:00:00")
        with self.assertRaises(BusinessException) as error:
            await resume_ppt(request, owner, self.db)
        self.assertEqual(error.exception.error_code, ErrorCode.OPERATION_ERROR)


if __name__ == "__main__":
    unittest.main()
