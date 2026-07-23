# DataWorks Agent

面向阿里云 DataWorks / MaxCompute 的多用户 Web Agent。项目直接 fork 当前活跃的 [`anomalyco/opencode`](https://github.com/anomalyco/opencode),保留 OpenCode 的 Coding Agent、Session、Provider、工具、SDK 与 SolidJS Web 能力,并新增 DataWorks OpenAPI、PyODPS、MCP、Skill、知识库和 RAG 能力。

> 当前状态:**实现分支 `upstream-base` 已具备可启动控制面 + DataWorks 工具/页面 + Skills/RAG 主路径**。唯一发布门禁是真实 staging（`bun run acceptance:staging`）；缺密钥硬失败，禁止 dry-run 充当发布通过。

## 已确认架构

- **上游基线**:`anomalyco/opencode@cd46f22d513d60b7a9bdca1111d25c50d2398355`(MIT)
- **核心运行时**:Bun + TypeScript + Effect + OpenCode SessionV2/ToolRegistry
- **Web**:OpenCode SolidJS + Vite + Tailwind,采用 new-api 风格的 OKLCH 视觉语言
- **多用户隔离**:控制面鉴权 + 每用户独立 OpenCode worker/data/config/root
- **DataWorks**:官方 TypeScript OpenAPI SDK + 常驻 PyODPS sidecar + 可选 MCP
- **凭证**:系统凭据库保护主密钥,AES-256-GCM 加密本地 `secrets.dat`;多用户 worker 不持有真实 LLM/DataWorks 密钥
- **LLM 出站**:控制面流式 Gateway 注入 Provider 凭证并执行来源/Provider 授权
- **测试**:集成测试为主；离线 dry-run 可选；**真实 staging 是唯一发布门禁**
- **嵌入模型**:MLE5 离线包，`manifest.json` 必须含真实 `archiveSha256`（产品路径 fail-closed，禁止静默 hash）

## 本地启动

```bash
# 推荐使用本机 bun 二进制（若 npm 包装损坏）
# Windows: C:/Users/Administrator/.bun/bin/bun.exe

bun run create-admin          # DWA_BOOTSTRAP_PASSWORD 或交互密码
HOST=127.0.0.1 PORT=8084 bun run start
# 开发: bun run dev:dataworks
```

`DATAWORKS_AGENT_DRY_RUN=1` 启动产品进程会以 **exit 2** 拒绝。

## 文档索引

| 文档 | 用途 |
|---|---|
| [设计 Spec](docs/superpowers/specs/2026-07-20-dataworks-agent-design.md) | 产品、架构与安全边界 |
| [实施计划](docs/superpowers/plans/2026-07-20-dataworks-agent-plan.md) | M0–M6 任务、依赖和验收步骤 |
| [贡献指南](CONTRIBUTING.md) | 分支、提交、PR 和测试规范 |
| [Staging 运维](docs/operations/staging.md) | 发布门禁与 staging 验收 |
| [备份恢复](docs/operations/backup-restore.md) | secrets.dat / 导出归档 |
| [上游同步](docs/operations/upstream-sync.md) | upstream-sync 排练 |
| [威胁模型](docs/security/threat-model.md) | 安全威胁与控制 |

## 验收与发布

```bash
# 唯一发布门禁：真实 staging（缺少密钥时硬失败，绝不 skip-as-pass）
# DATAWORKS_AGENT_DRY_RUN=1 会以 exit 2 拒绝
bun run acceptance:staging

# 可选离线套件（不是发布门禁）
bun run acceptance:dry-run

# 首次/更新嵌入模型（~1.3GB，写入 manifest 哈希；二进制本身不进 git）
bun scripts/fetch-embedding-model.ts

# 打包布局 + SHA256SUMS + SBOM + 第三方许可
bun run package:dataworks-agent
```

**发布完成条件（摘要）**

1. `acceptance:staging` exit 0（含读路径；写路径需 `DWA_STAGING_WRITE_TEST=1` + 专用可恢复资源）
2. Session 工具证明需 `DWA_STAGING_LLM_*`，否则 `releaseStagingGateComplete=false`
3. MLE5 `archiveSha256` 非 PENDING，本机已 `fetch-embedding-model` 抽出模型
4. 打包产物在干净机可启动（当前脚本可能生成 placeholder，需核 `artifacts/dist`）

发布由 `.github/workflows/release.yml` + release-please 驱动：仅签名 tag / 批准环境可发布，禁止从功能分支直接 publish。密钥与运维细节见 [Staging 运维](docs/operations/staging.md)。

## 目标仓库结构

```text
dataworks_agent/
├── packages/
│   ├── opencode/               # OpenCode runtime/server(上游)
│   ├── core/                   # OpenCode core(上游)
│   ├── app/                    # SolidJS Web(上游 + DataWorks 页面)
│   ├── ui/                     # OpenCode UI primitives
│   ├── dataworks-core/         # DataWorks 共享领域/Schema
│   ├── dataworks-control/      # 登录、用户、凭证、worker、API、RAG、审计
│   └── dataworks-plugin/       # OpenCode dw_* 工具与上下文扩展
├── sidecars/pyodps/            # MaxCompute 查询 sidecar
├── tests/integration/          # dry-run 与 staging 集成测试
├── docs/
├── UPSTREAM.md                 # 上游基线与同步策略
└── package.json                # Bun workspace
```
