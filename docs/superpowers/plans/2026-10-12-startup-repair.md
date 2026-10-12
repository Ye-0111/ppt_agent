# Startup and basic-function repair plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan inline. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing project installable and document a reproducible local startup, fixing reproduced startup and basic database/API bugs.

**Architecture:** Keep the current FastAPI/Vue structure and the backend workspace location. Load configuration from the repository root, package the actual backend directory, and provide an explicit non-destructive table initializer. Exercise services offline against a temporary SQL database; check MySQL DDL and actual dependency connectivity separately.

**Tech Stack:** Python 3.12, uv, FastAPI, SQLAlchemy 2.0, MySQL, Redis, Vue 3, Vite.

**Spec:** User request in this conversation, 2026-10-12: directly fix startup and basic-function problems and verify. Project constraints: `AGENTS.md`.

## Global Constraints

- Do not modify `handoff.md` or the user's `.env`.
- Announce changes before editing; keep repairs in the user's current checkout.
- Do not call paid model APIs or modify existing business data during verification.
- Leave changes uncommitted for the user to review.

## Review Focus

- Special characters in database/Redis passwords must survive URL construction.
- Fresh database tables must support the raw INSERT statements used by services.
- Startup failure must close resources and must not print passwords.
- Quota charging must be atomic and must not depend on callback arrival order.
- Resuming an outline must check task ownership and status before updating it.

### Task 1: Installation and configuration

**Files:** `pyproject.toml`, `ppt-backend/app/core/{config,database}.py`, `.env.example`, `tests/test_runtime_config.py`.
**Interfaces:** Repository-root `.env`; importable installed `app` package; existing backend-relative `workspace_path`.

- [x] Write and run configuration tests against a temporary repository layout, from both working directories, plus URL password round-trip tests. Expected: root `.env` and password tests fail before repair.
- [x] Fix package location and root `.env` lookup; align the default port/mode with the existing frontend and current workflow configuration.
- [x] Run configuration tests and build a wheel; verify it contains `app/main.py`.

### Task 2: Fresh schema and database initialization

**Files:** `ppt-backend/app/models/{user,ppt,ppt_template}.py`, `ppt-backend/app/init_db.py`, `tests/sqlite_database.py`, `tests/test_database_services.py`.
**Interfaces:** `python -m app.init_db` creates missing tables only; service INSERTs use server-side defaults.

- [x] Add real SQL service tests for registration, PPT task creation, and template upload. Expected: missing required database defaults fail.
- [x] Add server defaults and explicitly register all four models in the table initializer.
- [x] Verify service tests and compile MySQL DDL; verify the initializer preserves an existing row in a temporary database.

### Task 3: Basic task lifecycle and startup

**Files:** `ppt-backend/app/controller/ppt.py`, `ppt-backend/app/services/ppt_service.py`, `ppt-backend/app/core/redis.py`, `ppt-backend/app/main.py`, focused regression tests.
**Interfaces:** Existing SSE/API signatures; atomic task quota deduction; checked Redis connectivity.

- [x] Reproduce callback-order quota skipping, quota-exhaustion partial commit, missing task ownership check, and stale raw-SQL timestamps.
- [x] Repair only reproduced branches and add startup cleanup/password-log tests.
- [x] Verify the full offline suite. Keep unsupported experimental agent modes explicit in the runtime documentation rather than expanding their architecture in this task.

### Task 4: Run instructions and final verification

**Files:** `README.md`, `ppt-backend/docs/runtime.md`.
**Interfaces:** Root `uv sync --locked`, explicit database initialization, backend port 8001, frontend port 8200.

- [x] Document prerequisites, MySQL/Redis service commands, `.env` fields, database creation/initialization, and two-terminal startup.
- [x] Run the full offline suite, locked dependency sync, wheel-content check, and frontend build. Check configured MySQL/Redis without writes.
- [x] Obtain one fresh review of the final diff and tests; fix important findings with regression tests.
- [x] Report verified checks and the remaining external-service/model limits in the runtime guide; confirm handoff is unchanged.
