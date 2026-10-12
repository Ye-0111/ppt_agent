"""Subagents startup regressions with offline credentials."""

import json
import os
import subprocess
import sys
import unittest

import sqlite_database  # configure dummy secrets before loading the application


class SubAgentsStartupTests(unittest.TestCase):
    def test_uvicorn_loads_subagents_mode_with_all_specialist_tools(self):
        environment = os.environ.copy()
        environment["AGENT_MODE"] = "subagents"
        code = """
import json, sys
sys.path.insert(0, sys.argv[1])
from uvicorn import Config
config = Config('app.main:app', lifespan='off')
config.load()
from app.agent import multi_agent_impl
print(json.dumps({
    'agent': type(multi_agent_impl).__name__,
    'tools': [tool.name for tool in multi_agent_impl.sub_tools],
}))
"""
        result = subprocess.run(
            [sys.executable, "-c", code, str(sqlite_database.ROOT / "ppt-backend")],
            cwd=sqlite_database.ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        loaded = json.loads(result.stdout)
        self.assertEqual(loaded["agent"], "SubAgents")
        self.assertEqual(set(loaded["tools"]), {
            "outline_agent", "research_agent", "content_agent",
            "image_agent", "chart_agent", "beautify_agent",
        })


if __name__ == "__main__":
    unittest.main()
