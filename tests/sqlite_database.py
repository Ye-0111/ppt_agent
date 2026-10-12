"""Offline SQL adapter for service tests; mirrors MySQL execute's return contract."""

from contextlib import asynccontextmanager
from datetime import datetime
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

from sqlalchemy import Integer, MetaData, create_engine
from sqlalchemy.dialects import sqlite


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ppt-backend"))
os.environ.update({
    "DB_HOST": "127.0.0.1", "DB_NAME": "offline_test", "DB_USER": "test",
    "DB_PASSWORD": "dummy", "REDIS_HOST": "127.0.0.1", "REDIS_PASSWORD": "",
    "PASSWORD_SALT": "test-only", "DASHSCOPE_API_KEY": "test-key-not-real",
    "DASHSCOPE_MODEL": "test-model", "AGENT_MODE": "workflow",
    "USE_MULTI_AGENT": "true", "LANGSMITH_ENABLED": "false",
    "LANGSMITH_API_KEY": "", "LANGSMITH_TRACING": "false",
    "LANGCHAIN_TRACING_V2": "false", "PEXELS_API_KEY": "", "TAVILY_API_KEY": "",
    "MPLCONFIGDIR": "/private/tmp/ppt-agent-matplotlib-tests",
})


class SQLiteDatabase:
    def __init__(self, server_defaults=True):
        from app.core.database import Base
        from app.models import agent_log, ppt, ppt_template, user  # register tables

        self.temporary = tempfile.TemporaryDirectory()
        path = Path(self.temporary.name) / "test.sqlite"
        self.engine = create_engine(f"sqlite:///{path}")
        metadata = MetaData()
        for table in Base.metadata.sorted_tables:
            copied = table.to_metadata(metadata)
            # SQLite auto-increment requires INTEGER PRIMARY KEY, not BIGINT.
            copied.c.id.type = Integer()
            if not server_defaults:
                for column in copied.columns:
                    column.server_default = None
        metadata.create_all(self.engine)
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row

    def close(self):
        self.connection.close()
        self.engine.dispose()
        self.temporary.cleanup()

    def _execute(self, query, values=None):
        if not isinstance(query, str):
            compiled = query.compile(dialect=sqlite.dialect(paramstyle="named"))
            query, values = str(compiled), compiled.params
        if values:
            values = {
                key: value.isoformat(sep=" ") if isinstance(value, datetime) else value
                for key, value in values.items()
            }
        return self.connection.execute(query, values or {})

    @staticmethod
    def _row(row):
        if row is None:
            return None
        result = dict(row)
        for field in ("createTime", "updateTime", "startTime", "endTime"):
            if isinstance(result.get(field), str):
                result[field] = datetime.fromisoformat(result[field])
        return result

    async def execute(self, query, values=None):
        cursor = self._execute(query, values)
        if isinstance(query, str) and query.lstrip().upper().startswith("INSERT"):
            return cursor.lastrowid
        return cursor.rowcount

    async def fetch_one(self, query, values=None):
        return self._row(self._execute(query, values).fetchone())

    async def fetch_all(self, query, values=None):
        return [self._row(row) for row in self._execute(query, values).fetchall()]

    async def fetch_val(self, query, values=None):
        row = self._execute(query, values).fetchone()
        return row[0] if row else None

    @asynccontextmanager
    async def transaction(self):
        self.connection.execute("BEGIN")
        try:
            yield
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()
