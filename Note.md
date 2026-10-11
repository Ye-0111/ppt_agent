## 后端目录说明：
controller/控制器层

constants/常量

core/核心基础设施

models/数据模型层

schemas/数据校验层

services/服务处理层

utils/工具类

工作流程：schemas -> controller -> services -> models

## 注册登录实现
注册需要考虑的问题：
1. 验证前端发来的数据（参数校验）
2. 密码需要加密
3. 用户忘记密码的问题
4. 用户名防重
5. 异常处理

登录需要考虑的问题：
1. 验证
2. 密码出错时的提示
3. 异常处理
4. 异地登录
5. 加密后的匹配
6. 令牌 用Redis处理
7. 权限（数据权限、访问权限）

# 前端启动
npm run dev 打开浏览器 localhost:8200

# 后端启动
uv run uvicorn app.main:app --reload --port 8001

Agent = LLM + 记忆 + 规划 + 工具

三种接入方式：API接入、本地部署、SDK/框架接入

LangChain、LangGraph、LangSmith

接入大模型： ppt-backend/app/schemas/chat.py  ppt-backend/app/controller/chat.py

LangChain记忆流程：读取  注入  调用  保存

# 记忆模块
本项目中使用LangChain的混合摘要记忆组件SummaryBufferMemory

# 工具调用
流程：
意图识别
参数提取
工具执行
结果整合

项目里的自定义工具：
文件操作工具：读取、写入、列出文件
LangChain工具集-供ChatService绑定到大模型

工具调用常见设计模式：ReAct模式、Plan-and-Execute模式、Multi-Agent模式

# 规划策略
任务步骤明确 -> 是：PE模式 -> 过于复杂：Multi-Agent
        -> 否：ReAct模式
    
# 结构化输出
工作流程：
Schema定义 → with_structured_output绑定 → LLM原生解析 → 自动验证 → 返回类型化对象

# Skills
引入四个技能：
Pexels图片生成
图表生成
内容优化
PPT增强美化

# 流式响应
核心定义：流式响应是指LLM将生成的内容逐字/逐句实时返回给客户端，而非等待全部生成完毕后一次性返回。
工作流程：用户提问 → LLM逐token生成 → 实时推送到前端 → 前端逐字渲染

# 为什么需要多智能体
适合场景：复杂决策流程（如金融分析、内容审核）→ 人机协作系统（需人工审核节点）→ 多步骤迭代任务（如代码生成-审查-修复循环）
Subagents: Supervisor架构
多智能体并行：并发、独立、结果聚合、容错隔离

# 意图识别Router
Router比Supervisor更轻量、更专注
**可以使用Jev吗？SLO-Router?**

# DeepResearch
定义：Deep Research 是以大语言模型（LLM）为认知核心，通过实时检索外部知识、动态调用分析工具，自主管理端到端研究工作流的 AI Agent 系统
代码实现：使用Tavily--AI Agent Langchain官方集成的搜索基础设施
核心优势：低延迟180ms / 12+框架继承 / 零数据保留
避免过度设计，选择合适方案

# 实现模式
静态并行
动态并行

# Human-in-the-loop
HITL有三种模式：
人工确认、内容修改、路径选择
人工介入点在outline之后、research之前，用户审阅大纲，可以修改大纲

节点实现过程：
1. 定义中断节点
2. 读取 state 获取待审批内容
3. 触发中断等待输入
4. 获取人类决策结果
5. 根据决策更新 state 并返回

# 断点恢复

# PPT模板库

# LangSmith + Agent Log
LangSmith是LangChain官方推出的LLM应用开发与运维平台，提供从调试、测试到监控部署的全生命周期支持
Debugging、Testing、Monitoring、集成方式
LangSmith Trace追踪：
        机制核心概念：Trace（一次完整请求）→ Run（一次调用/步骤）→ Event（事件）  形成树状追踪结构