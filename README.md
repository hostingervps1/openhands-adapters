# openhands-adapters

> 拆迁模块接入层 — 将 vast-core 拆出的模块包装成 MCP Server，注册进 openhands 建站框架。

## 定位

```
vast-core/（拆迁产物）
    ↓
openhands-adapters/
    ├── register.py     # 把 vast-core 路由注册到 openhands 框架
    ├── auth.py         # 认证适配层
    └── config.py       # 配置适配层
    ↓
openhands 建站框架（消费方）
```

## 注册点

| 模块 | 来源 | 注册方式 |
|------|------|----------|
| `get_current_user` | `02-auth/utils/auth.py` | openhands 认证中间件 |
| 全部 `router` | `05-routers/` | openhands 路由注册 |
| `AppConfig` | `07-config/core.py` | openhands 配置中心 |

## 万能拆迁流水线 — 完整设计规范

### 总流水线结构

```
[N01] Trigger
  ↓
[N02] Object Adapter（标准化）
  ↓
[N03] Object Router（分流）
  ↓
[N04] Pre-Check / 去重
  ↓
[N05] Split In Batches
  ↓
[N06A] Understand CLI ──┐
[N06B] Sonargraph      ─┤ 并行（禁止AI介入）
[N06C] AST 精准扫描    ─┘
  ↓
[N07] Normalize（结构归一）
  ↓
[N08] Store DB（持久化）
  ↓
[N09] AI Reasoner（理解层）
  ↓
[N10] Result Router
  ↓
[N11] Package & 说明书
  ↓
[N12] Output / 通知 / 注册
```

### 核心原则

- **拆 ≠ 复制**：先 100% 摸清结构，再按依赖最小化抽取，每个改动必须有标注和原因。
- **验收门禁铁律**：不全绿不往下走，回流到对应步骤修。
- **AI 最后才出现**：N06 扫描产出的是事实，N09 AI 做的是理解与建议，顺序不能反。
- **工具可换，数据结构不能乱**：N07 Normalize Node 是整条流水线最值钱的一层。

## 节点详细设计

### 第一组：触发与标准化

#### N01 — Trigger
**工具**：`n8n Webhook Node`

做什么：接收"我要拆一个对象"的请求，支持三种触发方式：Webhook（外部事件驱动）、Schedule（定时批量）、Manual（调试/测试）。

为什么必须有：所有自动化的硬入口。统一入口意味着权限、审计、限流全部集中管控，不允许流程从中间节点启动。

加强方向：多 Trigger 合并同一主流程；Header 注入 `X-Request-Id` 用于全链路审计；加 rate limiting 防止打爆。

#### N02 — Object Adapter
**工具**：`n8n Code Node`

做什么：把任意格式的输入转换成「万能拆标准对象」。后续所有节点都消费这个统一格式，不关心原始来源是什么。

为什么必须有：万能拆能不能复用，取决于这一层是否稳定。只要入口格式千变万化、出口格式不变，整条流水线就是可插拔的。

```json
{
  "object_id": "uuid-v4",
  "object_type": "code",
  "source": { "type": "git", "location": "https://..." },
  "raw_pointer": "/workspace/project",
  "meta": { "language": "python", "hash": "sha256:..." },
  "priority": "normal",
  "created_at": "ISO8601"
}
```

#### N03 — Object Router
**工具**：`n8n Switch Node`

做什么：根据 `object_type` 路由到对应子流程。`code` 走代码拆解链，`api` 走 API 拆解链，`db` 走数据库拆解链，`container` 走镜像拆解链。

验收门禁：未识别类型 → fallback 节点（人工标注 or AI 猜测），不能直接失败丢弃。

### 第二组：预处理与稳定性

#### N04 — Pre-Check / 去重
**工具**：`n8n Postgres Node + IF Node`

做什么：查询状态数据库，判断该对象是否已拆过（`done`）、正在拆（`running`）、还是第一次（`new`）。

验收门禁：状态 = `running` → 等待；状态 = `done` → 直接返回缓存结果，流程终止。

#### N05 — Split In Batches
**工具**：`n8n Split In Batches Node`

做什么：将大型对象切分成批次，控制并发，避免拆解工具内存溢出或超时。

验收门禁：单批失败 → 记录失败批次，其余批次继续，全部完成后汇总失败列表。

### 第三组：拆解引擎（禁止 AI 介入）

> ⚠️ 本组节点严禁 AI 参与。扫描结果必须 100% 可信，AI 会产生幻觉。

#### N06A — Understand CLI
**工具**：`und CLI（SciTools）`

做什么：工业级静态分析，输出函数/类/模块的调用关系、度量指标（圈复杂度、耦合度、行数）、模块级依赖图。

验收门禁：退出码非 0 → 流程停止，报错存档，等待人工。

#### N06B — Sonargraph 并行
**工具**：`Sonargraph CLI / API`

做什么：与 N06A 并行运行，专注架构规则检查：循环依赖、分层违规、包结构混乱。

验收门禁：发现 `critical` 级别违规 → 标记为需人工确认，不阻塞流程，但最终报告必须包含。

#### N06C — AST 精准扫描
**工具**：`Python ast / tree-sitter / babel-parser`

做什么：秒级扫描每个文件的精确 import 列表、函数签名、类定义。作为后续 AI 推理的事实基础，防止 AI 凭空捏造依赖关系。

验收门禁：解析失败的文件 → 单独存档，不影响其他文件。

### 第四组：结构归一与持久化

#### N07 — Normalize Node
**工具**：`n8n Code Node / 独立 Python 微服务`

做什么：把三个工具的输出归一化成统一 4 表结构：Entity（实体）、Relation（关系）、Metric（度量）、Snapshot（快照）。工具可以换，数据结构绝不能乱。

```json
{
  "entities": [{ "id": "uuid", "name": "AuthService", "type": "class", "layer": 2 }],
  "relations": [{ "from_id": "uuid-A", "to_id": "uuid-B", "type": "depends_on", "confidence": 1.0 }],
  "metrics": {},
  "snapshot": { "object_id": "...", "analyzed_at": "ISO8601" }
}
```

验收门禁：三工具结果冲突 → 标记 `confidence < 1.0`，存入 `review_queue`。

#### N08 — Store DB
**工具**：`n8n Postgres Node`

做什么：写入 Postgres，分两个 schema：`facts`（只写不改）和 `ai_analysis`（可更新）。两者严格分离，AI 不能覆盖事实数据。

验收门禁：写入失败 → 流程暂停，等待 DB 恢复，不丢数据。

### 第五组：AI 理解层

#### N09 — AI Reasoner
**工具**：`Claude API / OpenRouter（ANALYZE key）`

做什么：AI 在这里才第一次登场。输入是归一化后的结构数据（不是原始代码），输出模块职责总结、风险识别、拆解建议（留 / 删 / 改 / 内联）。

```json
{
  "summary": "这个模块负责用户认证，依赖 UserModel 和 JWT 工具层",
  "risks": [{ "type": "cycle", "modules": ["A","B"], "severity": "high" }],
  "suggestions": [{ "module": "LicenseChecker", "action": "remove", "reason": "[REMOVED] 商业特性" }]
}
```

验收门禁：AI 输出必须能 `JSON.parse()`；失败 → 重试 2 次，仍失败 → 标记 `needs_review`。

加强方向：多模型投票（Sonnet + Gemini + GPT）；不同角色 Prompt（架构师 / 运维 / 安全）。

### 第六组：结果分发与闭环

#### N10 — Result Router
**工具**：`n8n Switch Node`

做什么：按风险等级分流——`critical` → 创建任务等待人工，`normal` → 进入打包，`error` → 触发告警。

#### N11 — Package & 说明书
**工具**：`n8n Code Node + Shell`

做什么：按标准目录结构打包（Layer 0 → N 分目录），自动生成说明书（模块职责、注册方式、环境变量、接口签名）。

验收门禁：包内文件数与预期不符 → 停止，报告缺失文件。

#### N12 — Output / 通知 / 注册
**工具**：`n8n HTTP Request Node + Gitea API`

做什么：三件事并行——推送到 Gitea、写入文档系统、发送完成通知。如果注册到 MCP 大脑，额外调用注册 API。

验收门禁：Gitea 推送失败 → 重试 3 次，仍失败 → 本地存档 + 人工通知。

## 标注规范

每个拆迁文件必须遵守以下标注：

| 标注 | 含义 |
|------|------|
| `[IMPORT_CHANGE]` | import 路径从绝对改为相对，或从 env.py 改为 os.environ |
| `[REMOVED]` | 删掉的功能块（License/OTEL/商业特性），说明原因 |
| `[KEPT]` | 保留的关键逻辑，说明为什么不能删 |
| `[INLINED]` | 从 utils/misc.py 等工具文件内联进来的函数 |
| `[CIRCULAR_IMPORT]` | 循环依赖处理，改为延迟导入（在函数体内 import） |
| `[ENV]` | 从 os.environ 读取的配置变量 |
| `[ADDED]` | 新增参数或逻辑 |

## 基础设施

| 组件 | 地址 |
|------|------|
| VPS | `62.72.1.199` |
| n8n | `https://n8n.srv1403503.hstgr.cloud` |
| Gitea | `http://62.72.1.199:3000` |
| AI 接入 | OpenRouter（三角色 key 体系：ANALYZE / EXECUTE / VERIFY） |

## 相关仓库

| 仓库 | 说明 |
|------|------|
| [disassembly-pipeline](https://github.com/hostingervps1/disassembly-pipeline) | 流水线设计规范与 n8n 工作流 |
| [hermes-agent](https://github.com/hostingervps1/hermes-agent) | 自我改进 AI 智能体核心 |
| [vast-core](https://github.com/hostingervps1/vast-core) | OpenWebUI 后端拆迁产物 |
| [normalize-service](https://github.com/hostingervps1/normalize-service) | 多工具输出归一化服务 |
| [openhands-adapters](https://github.com/hostingervps1/openhands-adapters) | 本仓库 — 拆迁模块接入层 |
