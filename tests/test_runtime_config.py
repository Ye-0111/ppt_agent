"""Configuration regressions, using dummy secrets and isolated .env files."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "ppt-backend/app/core/config.py"
DUMMY_ENV = """DB_HOST=127.0.0.1
DB_NAME=startup_test
DB_USER=test_user
DB_PASSWORD=test@pass/#:%
REDIS_HOST=127.0.0.1
REDIS_PASSWORD=redis@pass/#:%
PASSWORD_SALT=test-only-salt
"""


class RuntimeConfigTests(unittest.TestCase):
    def inspect_config(self, working_directory, duplicate_backend_env=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copied = root / "ppt-backend/app/core/config.py"
            copied.parent.mkdir(parents=True)
            shutil.copyfile(CONFIG, copied)
            (root / ".env").write_text(DUMMY_ENV)
            if duplicate_backend_env:
                (root / "ppt-backend/.env").write_text(DUMMY_ENV)
            environment = os.environ.copy()
            for name in list(environment):
                if name.startswith(("DB_", "REDIS_")) or name == "PASSWORD_SALT":
                    environment.pop(name)
            code = """
import importlib.util, json, sys
from sqlalchemy.engine import make_url
from urllib.parse import urlsplit, unquote
from pydantic import ValidationError
spec = importlib.util.spec_from_file_location('runtime_config', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
try:
    spec.loader.exec_module(module)
except ValidationError as error:
    print(json.dumps({'missing': [str(e['loc'][0]) for e in error.errors(include_input=False)]}))
else:
    settings = module.settings
    try:
        url = make_url(settings.database_url)
        print(json.dumps({'database': url.database, 'db_password': url.password,
            'redis_password': unquote(urlsplit(settings.redis_url).password or ''),
            'workspace': str(settings.workspace_path.relative_to(module.BASE_DIR))}))
    except ValueError:
        print(json.dumps({'url_error': 'invalid connection URL'}))
"""
            result = subprocess.run(
                [sys.executable, "-c", code, str(copied)],
                cwd=root / working_directory,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
            return json.loads(result.stdout)

    def test_root_env_is_loaded_from_both_working_directories(self):
        for cwd in (".", "ppt-backend"):
            with self.subTest(cwd=cwd):
                result = self.inspect_config(cwd)
                self.assertEqual(result.get("database"), "startup_test", result)
                self.assertEqual(result["workspace"], "workspace")

    def test_special_characters_in_connection_passwords_round_trip(self):
        result = self.inspect_config(".", duplicate_backend_env=True)
        self.assertEqual(result.get("db_password"), "test@pass/#:%", result)
        self.assertEqual(result.get("redis_password"), "redis@pass/#:%", result)

    def test_async_database_preserves_driver_name_text_in_password(self):
        environment = os.environ.copy()
        environment.update(dict(line.split("=", 1) for line in DUMMY_ENV.splitlines()))
        environment["DB_PASSWORD"] = "a+pymysqlb"
        code = """
import json, sys
sys.path.insert(0, sys.argv[1])
from app.core.database import database
print(json.dumps({'password': database.url.password}))
"""
        result = subprocess.run(
            [sys.executable, "-c", code, str(ROOT / "ppt-backend")],
            cwd=ROOT, env=environment, capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(result.stdout)["password"], "a+pymysqlb")


if __name__ == "__main__":
    unittest.main()
