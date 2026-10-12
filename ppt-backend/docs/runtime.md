# 本地运行

以下流程以 macOS + Homebrew 为例。命令中的 `ppt_agent` 是示例数据库名；如果保留现有数据库，请让它与根目录 `.env` 的 `DB_NAME` 一致。

## 1. 准备工具与服务

需要 Python 3.12、uv、Node.js 22.12 或以上版本、MySQL 和 Redis。当前机器已有 Python、uv、Node.js 和 Redis，但检查时 MySQL、Redis 都无法连接。

```bash
brew install mysql@8.4 redis
brew services start mysql@8.4
brew services start redis
```

`mysql@8.4` 的命令没有自动加入 PATH，下面通过 Homebrew 的安装目录调用。新装的 Homebrew MySQL 默认 root 密码为空；已有安装按自己的密码连接。参见 [MySQL 8.4](https://formulae.brew.sh/formula/mysql@8.4)、[Redis](https://formulae.brew.sh/formula/redis) 和 [Vite Node.js 要求](https://vite.dev/guide/)。

```bash
"$(brew --prefix mysql@8.4)/bin/mysql" -u root -p -e "CREATE DATABASE IF NOT EXISTS ppt_agent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
redis-cli ping
```

MySQL 会提示输入密码，新装的空密码直接回车；Redis 应返回 `PONG`。如果 Redis 设置了密码，验证命令和 `.env` 也需要使用对应密码。

## 2. 安装依赖并配置 `.env`

```bash
cd /Users/murrayz/code/PPT_Agent
uv sync --locked
```

从 GitHub 克隆到其他目录时，把 `cd` 路径替换为实际位置。`uv sync` 会安装锁文件中的依赖，并将 `ppt-backend/app` 以可编辑方式安装成 `app` 包；不用手动激活 `.venv` 或设置 `PYTHONPATH`。参见 [uv 项目运行说明](https://docs.astral.sh/uv/guides/projects/)。

配置文件统一放在仓库根目录。当前项目已有 `.env`，直接编辑已有文件，保留自己的 API key。首次克隆且没有 `.env` 时执行：

```bash
cp .env.example .env
```

检查以下字段：

| 字段 | 本地开发设置 |
| --- | --- |
| `DB_HOST` / `DB_PORT` | `127.0.0.1` / `3306` |
| `DB_NAME` | 与刚创建的数据库一致，例如 `ppt_agent` |
| `DB_USER` / `DB_PASSWORD` | 本机 MySQL 用户和密码；空密码写 `DB_PASSWORD=` |
| `REDIS_HOST` / `REDIS_PORT` | `127.0.0.1` / `6379` |
| `REDIS_PASSWORD` | 与 Redis 一致；未设密码时写 `REDIS_PASSWORD=` |
| `PASSWORD_SALT` | 自己生成的随机值，注册用户后保持不变 |
| `DASHSCOPE_API_KEY` / `DASHSCOPE_MODEL` | 有效的通义千问 API key 和账户可用的模型名称，例如 `qwen-plus` |
| `USE_MULTI_AGENT` / `AGENT_MODE` | `true` / `workflow` |
| `OUTLINE_REVIEW_ENABLED` | `true` 开启大纲审阅；`false` 直接生成 |
| `LANGSMITH_ENABLED` | 初次运行建议 `false`；配置 tracing 时再开启 |

`PEXELS_API_KEY` 和 `TAVILY_API_KEY` 分别用于配图与联网研究，可留空；这些能力会降级跳过。LangSmith 是可选项。`AGENT_MODE` 只接受 `workflow` 或 `subagents`，其他拼写（如 `subagent`）会在启动配置校验时被拒绝。完整的创作、大纲审阅和断点续跑接口要求 `USE_MULTI_AGENT=true` 且 `AGENT_MODE=workflow`；当前 `subagents` 实验入口尚未实现全部接口，PPT 接口会在创建任务或扣配额前拒绝不兼容的配置。

可以生成盐值后填入 `.env`：

```bash
uv run python -c 'import secrets; print(secrets.token_hex(32))'
```

## 3. 初始化数据库表

数据库必须已创建，连接字段也必须填写正确。

```bash
uv run python -m app.init_db
```

这会创建缺失的四张表：`sys_user`、`sys_ppt`、`sys_ppt_template`、`sys_agent_log`，不会删除已有数据。可以重复执行。已有表的字段和默认值不会自动迁移；旧表如果缺少 `stage`、`outline`、`research`、`sessionId` 等字段，需要按当前模型单独迁移。服务的原生 SQL 已显式写入必需的状态和时间字段，已有表无需仅为默认值重新建表。

## 4. 在两个终端启动

终端 A：后端，工作目录是仓库根目录。

```bash
cd /Users/murrayz/code/PPT_Agent
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

访问 `http://localhost:8001/docs` 查看 API 文档。命令显式指定 8001，避免现有 `.env` 中其他 `SERVER_PORT` 值与前端不一致。后端会验证 MySQL 和 Redis 连接；任一不可用时会启动失败。

终端 B：前端。

```bash
cd /Users/murrayz/code/PPT_Agent/ppt-frontend
npm ci
npm run dev -- --strictPort
```

打开 **http://localhost:8200**。前端 API 地址当前固定为 `http://localhost:8001/api`，CORS 允许 `http://localhost:8200`。按这里的主机名与端口访问，然后注册、登录并创建 PPT。端口占用时 `--strictPort` 会直接报错，避免 Vite 自动换端口后跨域失败。

生成文件和上传模板保存在 `ppt-backend/workspace/`，已被 Git 忽略。要停止前后端，在各自终端按 Ctrl+C；要停止本地服务可以执行 `brew services stop mysql@8.4` 和 `brew services stop redis`。

## 5. 自检命令

```bash
# 仓库根目录：离线回归测试，不调用模型，也不访问业务库
uv run python -m unittest discover -s tests -v

# 后端启动后：预期返回 code=0
curl http://localhost:8001/api/hello

# 前端目录：类型检查和生产构建
cd ppt-frontend
npm run build
```

当前离线测试使用临时 SQLite 执行服务 SQL、内存会话缓存验证 HTTP 登录流程，以及外部连接替身检查启动清理。它们不能替代真实 MySQL、Redis、模型 API 和浏览器端到端验证。模型调用会消耗账户配额；本次检查没有调用模型。

本次修复后的验证结果：26 项离线回归测试通过；锁定依赖安装、包含后端代码的 wheel 构建、前端类型检查和生产构建通过；临时 Redis 的 PING、特殊密码认证、登录令牌保存/读取/注销通过；前端开发服务器在 8200 端口返回页面。临时服务已关闭，未修改现有业务数据。

已修复根目录配置读取、后端打包路径、新旧数据库表的必需字段写入、启动失败资源清理、密码日志输出、任务扣额度/断点恢复、任务归属校验，以及刷新后登录恢复和服务端注销。生成文件名与扣额度现在在同一事务提交；旧版本留下的未扣额度文件在恢复前补扣。

检查范围限于启动和上述基础功能；真实 MySQL 事务并发、模型生成质量、浏览器 cookie/CORS 的完整流程，以及全仓库安全审计仍未验证。当前配置的 MySQL/Redis 服务检查时均不可连接；临时 Redis 验证不代表已有服务配置已就绪。前端构建还有产物体积超过 500 kB 的提示，本次未处理性能拆包。修复留在当前工作目录，尚未提交；`handoff.md` 和已有 `.env` 未修改。

## 常见启动错误

- `ValidationError` 提示数据库配置缺失：检查仓库根目录的 `.env`，字段名对照 `.env.example`。
- MySQL `2003` / connection refused：服务未启动或地址、端口不匹配。
- MySQL `1045`：用户或密码错误；不要沿用其他电脑上的密码。
- MySQL `1049`：数据库尚未创建或 `DB_NAME` 不匹配。
- `Table ... doesn't exist`：执行 `uv run python -m app.init_db`。
- `Unknown column`：已有表结构较旧，需要数据库迁移；初始化命令不会覆盖已有表。
- Redis connection refused / authentication error：启动服务，并让 `.env` 的 Redis 地址和密码与实际配置一致。
- OpenAI/DashScope key 错误：填写 `DASHSCOPE_API_KEY`；此项目调用的是 DashScope 的 OpenAI 兼容接口。
- 后端能访问、前端请求失败：确保使用 `localhost:8200`，后端端口为 8001。
