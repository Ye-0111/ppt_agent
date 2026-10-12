# PPT Agent

基于 FastAPI、Vue 和 LangGraph 的 PPT 创作项目，支持聊天、PPT 生成、大纲审阅、模板上传和任务续跑。

完整的安装、数据库配置和启动流程见 **[本地运行指南](ppt-backend/docs/runtime.md)**。配置样例在 [.env.example](.env.example)，实际 `.env` 不提交到 Git。

后端从仓库根目录运行：

```bash
uv sync --locked
uv run python -m app.init_db
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

执行前先按运行指南准备 MySQL、Redis、数据库和 `.env`。

前端另开终端运行：

```bash
cd ppt-frontend
npm ci
npm run dev -- --strictPort
```

页面地址：<http://localhost:8200>；API 文档：<http://localhost:8001/docs>。

离线回归测试：

```bash
uv run python -m unittest discover -s tests -v
```
