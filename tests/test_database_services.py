import unittest
from sqlalchemy import create_engine, inspect

from sqlite_database import SQLiteDatabase
from app.schemas.user import UserRegisterRequest, UserLoginRequest
from app.services.user_service import UserService
from app.services.ppt_service import PptService
from app.services.ppt_template_service import PptTemplateService


class FreshSchemaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = SQLiteDatabase()

    def tearDown(self):
        self.db.close()

    async def test_registration_and_login_work_with_fresh_schema_defaults(self):
        service = UserService(self.db)
        uid = await service.register(UserRegisterRequest(
            username="test_user", password="test-password", checkPassword="test-password",
        ))
        user = await service.login(UserLoginRequest(username="test_user", password="test-password"))
        self.assertEqual(user.id, uid)
        self.assertEqual(user.ppt_quota, 10)
        self.assertTrue(user.create_time)
        row = await self.db.fetch_one("SELECT status FROM sys_user WHERE id=:id", {"id": uid})
        self.assertEqual(row["status"], 1)

    async def test_task_creation_and_list_work_with_fresh_schema_defaults(self):
        service = PptService(self.db)
        pid = await service.create_task(1, "Test topic", "business", "test-session")
        task = await service.get_task(pid, 1)
        self.assertEqual(task["stage"], "CREATED")
        self.assertEqual(task["status"], "IN_PROGRESS")
        self.assertTrue(task["createTime"])
        self.assertTrue(task["updateTime"])
        listing = await service.list_by_user(1, 1, 10)
        self.assertEqual(listing["total"], 1)

    async def test_template_upload_insert_gets_database_timestamps(self):
        service = PptTemplateService(self.db)
        tid = await service.create(1, "Test template", "test.pptx", '["title"]', 1, 0)
        row = await self.db.fetch_one("SELECT * FROM sys_ppt_template WHERE id=:id", {"id": tid})
        self.assertEqual(row["name"], "Test template")
        self.assertIsNotNone(row["createTime"])
        self.assertIsNotNone(row["updateTime"])

    async def test_initializer_creates_all_tables_and_preserves_existing_rows(self):
        try:
            from app.init_db import initialize_database
        except ImportError:
            self.fail("The database initializer is unavailable")
        empty = create_engine("sqlite:///:memory:")
        try:
            initialize_database(empty)
            self.assertEqual(set(inspect(empty).get_table_names()), {
                "sys_user", "sys_ppt", "sys_ppt_template", "sys_agent_log",
            })
        finally:
            empty.dispose()
        await self.db.execute(
            "INSERT INTO sys_user (username,password,userRole,ppt_quota,status,createTime) "
            "VALUES ('existing','dummy','user',3,1,CURRENT_TIMESTAMP)"
        )
        initialize_database(self.db.engine)
        self.assertEqual(await self.db.fetch_val("SELECT ppt_quota FROM sys_user WHERE username='existing'"), 3)


class ExistingSchemaTests(FreshSchemaTests):
    """Repairs must also work without changing already-created table defaults."""

    def setUp(self):
        self.db = SQLiteDatabase(server_defaults=False)


if __name__ == "__main__":
    unittest.main()
