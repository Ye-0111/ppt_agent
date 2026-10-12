import contextlib
import io
import unittest
from unittest.mock import AsyncMock, patch

import sqlite_database  # configure dummy secrets before importing the application
from app import main
from app.core import redis as redis_module


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_does_not_print_connection_passwords(self):
        output = io.StringIO()
        with patch.object(main.database, "connect", new=AsyncMock()), \
             patch.object(main.database, "is_connected", True), \
             patch.object(main.database, "disconnect", new=AsyncMock()), \
             patch.object(main, "init_redis", new=AsyncMock()), \
             patch.object(main, "close_redis", new=AsyncMock()), \
             contextlib.redirect_stdout(output):
            async with main.lifespan(main.app):
                pass
        self.assertNotIn("dummy", output.getvalue())

    async def test_failed_redis_startup_disconnects_database(self):
        disconnect = AsyncMock()
        with patch.object(main.database, "connect", new=AsyncMock()), \
             patch.object(main.database, "is_connected", True), \
             patch.object(main.database, "disconnect", new=disconnect), \
             patch.object(main, "init_redis", new=AsyncMock(side_effect=ConnectionError("offline"))), \
             patch.object(main, "close_redis", new=AsyncMock()):
            with self.assertRaises(ConnectionError):
                async with main.lifespan(main.app):
                    pass
        disconnect.assert_awaited_once()

    async def test_redis_initialization_checks_connectivity_and_closes_on_failure(self):
        client = AsyncMock()
        client.ping.side_effect = ConnectionError("offline")
        with patch.object(redis_module.redis, "from_url", return_value=client):
            try:
                with self.assertRaises(ConnectionError):
                    await redis_module.init_redis()
                client.aclose.assert_awaited_once()
                self.assertIsNone(redis_module.redis_client)
            finally:
                redis_module.redis_client = None


if __name__ == "__main__":
    unittest.main()
