import unittest
from unittest.mock import patch

import httpx
from sqlite_database import SQLiteDatabase
from app.core.database import get_db
from app.core import redis as redis_module
from app.main import app


class SessionCache:
    """In-memory replacement for the external Redis transport in API tests."""

    def __init__(self):
        self.values = {}

    async def setex(self, key, seconds, value):
        self.values[key] = value

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        return int(self.values.pop(key, None) is not None)


class UserAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = SQLiteDatabase()
        async def database_override():
            yield self.db
        app.dependency_overrides[get_db] = database_override
        self.cache = SessionCache()
        self.cache_patch = patch.object(redis_module, "redis_client", self.cache)
        self.cache_patch.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.cache_patch.stop()
        app.dependency_overrides.pop(get_db, None)
        self.db.close()

    async def login(self):
        registered = await self.client.post("/api/user/register", json={
            "username": "api_user", "password": "test-password", "checkPassword": "test-password",
        })
        self.assertEqual(registered.json()["code"], 0)
        result = await self.client.post("/api/user/login", json={"username": "api_user", "password": "test-password"})
        self.assertEqual(result.json()["code"], 0)
        self.assertIn("TOKEN", self.client.cookies)
        return registered.json()["data"]

    async def test_login_cookie_restores_user_and_current_quota(self):
        uid = await self.login()
        await self.db.execute("UPDATE sys_user SET ppt_quota=4 WHERE id=:id", {"id": uid})
        response = await self.client.get("/api/user/get/login")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["id"], uid)
        self.assertEqual(response.json()["data"]["pptQuota"], 4)

    async def test_logout_revokes_cookie_and_server_session(self):
        await self.login()
        old_token = self.client.cookies["TOKEN"]
        response = await self.client.post("/api/user/logout")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 0)
        self.assertNotIn("TOKEN", self.client.cookies)
        replay = await self.client.post("/api/ppt/list", json={}, headers={"Cookie": f"TOKEN={old_token}"})
        self.assertEqual(replay.json()["code"], 40100)

    async def test_hello_and_openapi_are_accessible(self):
        response = await self.client.get("/api/hello")
        self.assertEqual(response.json()["code"], 0)
        spec = (await self.client.get("/openapi.json")).json()
        self.assertIn("/api/ppt/create", spec["paths"])


if __name__ == "__main__":
    unittest.main()
