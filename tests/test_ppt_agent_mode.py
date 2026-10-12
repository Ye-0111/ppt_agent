"""Reject incompatible PPT engines before persisting task changes."""

import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from sqlite_database import SQLiteDatabase
from app.agents.subagents import SubAgents
from app.agents.workflow.graph import build_outline_only_graph
from app.controller import ppt as ppt_controller
from app.core.config import Settings, settings
from app.core.exceptions import BusinessException, ErrorCode
from app.schemas.ppt import PptCreateRequest, PptOutlineResumeRequest, PptResumeRequest
from app.schemas.user import LoginUserVO
from app.services.ppt_service import PptService
from app.services import agent_log_service


class OutlineChatModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class AgentModeConfigTests(unittest.TestCase):
    def test_invalid_agent_modes_are_rejected_instead_of_selecting_subagents(self):
        for mode in ("subagent", "worklfow", "unknown"):
            with self.subTest(mode=mode):
                with self.assertRaises(ValidationError):
                    Settings(_env_file=None, agent_mode=mode)


class PPTAgentModeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = SQLiteDatabase()
        await self.db.execute(
            "INSERT INTO sys_user (id,username,password,ppt_quota) VALUES (1,'owner','dummy',2)"
        )
        self.service = PptService(self.db)
        self.pid = await self.service.create_task(1, "Test", "business", "u1")
        self.user = LoginUserVO(
            id=1, username="owner", userRole="user", createTime="2026-10-12T00:00:00"
        )
        self.workflow_agent = ppt_controller.default_stream_agent
        self.agent_patch = patch.object(ppt_controller, "default_stream_agent", SubAgents())
        self.agent_patch.start()
        self.addCleanup(self.agent_patch.stop)
        self.addCleanup(self.db.close)

    async def assert_mode_rejected(self, action):
        with self.assertRaises(BusinessException) as error:
            await action
        self.assertEqual(error.exception.error_code, ErrorCode.OPERATION_ERROR)
        self.assertIn("AGENT_MODE=workflow", error.exception.message)
        self.assertEqual(await self.db.fetch_val("SELECT COUNT(*) FROM sys_ppt"), 1)
        self.assertEqual(await self.service.get_quota(1), 2)

    async def test_outline_review_rejects_subagents_before_creating_task(self):
        with patch.object(settings, "outline_review_enabled", True):
            await self.assert_mode_rejected(ppt_controller.create_ppt(
                PptCreateRequest(message="Test"), self.user, self.db
            ))

    async def test_direct_creation_rejects_subagents_before_creating_task(self):
        with patch.object(settings, "outline_review_enabled", False):
            await self.assert_mode_rejected(ppt_controller.create_ppt(
                PptCreateRequest(message="Test"), self.user, self.db
            ))

    async def test_outline_resume_rejects_subagents_before_updating_outline(self):
        await self.assert_mode_rejected(ppt_controller.resume_ppt(
            PptOutlineResumeRequest(
                message="Test", outline='[{"title":"One","purpose":"Intro"}]', pptId=self.pid
            ), self.user, self.db
        ))
        task = await self.service.get_task(self.pid, 1)
        self.assertIsNone(task["outline"])
        self.assertEqual(task["stage"], "CREATED")

    async def test_task_resume_rejects_subagents_before_charging_legacy_file(self):
        await self.service.update_progress(self.pid, filename="uncharged.pptx")
        await self.assert_mode_rejected(ppt_controller.resume_ppt_task(
            PptResumeRequest(pptId=self.pid), self.user, self.db
        ))
        task = await self.service.get_task(self.pid, 1)
        self.assertEqual(task["stage"], "CREATED")

    async def test_workflow_outline_review_emits_outline_and_persists_without_charging(self):
        outline = '[{"title":"Test","layout_hint":"title-slide","purpose":"Intro"}]'
        model = OutlineChatModel(responses=[AIMessage(content=outline)])
        graph = build_outline_only_graph(model, checkpointer=MemorySaver())
        with patch.object(ppt_controller, "default_stream_agent", self.workflow_agent), \
             patch.object(self.workflow_agent, "outline_graph", graph), \
             patch.object(agent_log_service, "database", self.db), \
             patch.object(settings, "outline_review_enabled", True):
            response = await ppt_controller.create_ppt(
                PptCreateRequest(message="Test"), self.user, self.db
            )
            chunks = [chunk async for chunk in response.body_iterator]
        events = [json.loads(chunk.removeprefix("data: ")) for chunk in chunks]
        self.assertNotIn("ERROR", [event["type"] for event in events])
        review = next(event for event in events if event["type"] == "OUTLINE_REVIEW")
        self.assertEqual(json.loads(review["outline"]), [
            {"title": "Test", "layout_hint": "title-slide", "purpose": "Intro"}
        ])
        done = next(event for event in events if event["type"] == "DONE")
        task = await self.service.get_task(done["pptId"], 1)
        self.assertEqual(task["stage"], "OUTLINE_DONE")
        self.assertEqual(json.loads(task["outline"]), json.loads(review["outline"]))
        self.assertEqual(task["status"], "IN_PROGRESS")
        self.assertEqual(await self.service.get_quota(1), 2)


if __name__ == "__main__":
    unittest.main()
