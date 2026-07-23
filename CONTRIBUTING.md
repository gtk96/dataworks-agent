# 贡献指南

## 分支策略

- `main`:受保护,只接受 PR 合并。
- `<scope>-<short-desc>`:工作分支,最多 3 个短横线分隔词,不使用 `/`,如 `dw-jobs-list`。
- `upstream-sync`:合入 `upstream/dev` 的专用分支,必须跑全量回归。
- `release-vX.Y.Z`:发布分支,只允许文档、版本与发布修复。

## 提交规范(Conventional Commits)

```
<type>(<scope>): <subject>

<body>

<footer>
```

- `feat`:新功能
- `fix`:修复
- `refactor`:重构(无新功能/无修复)
- `docs`:仅文档
- `test`:仅测试
- `chore`:构建/工具/杂项
- `perf`:性能

示例:`feat(dwtools): add dw_table_lineage tool`。

## PR 要求

- 通过单元测试 + 集成测试(若涉及)。
- 至少 1 位评审。
- PR 描述必须含:
  - 改了什么、为什么
  - 影响范围
  - 验证步骤(staging 截图/日志)
  - 风险与回滚方案
- 功能分支频繁小提交,便于审阅和回滚。
- 合并统一使用 **Squash merge**,`main` 保持一 PR 一 Conventional Commit。

## 评审门禁

- 命名、错误处理、安全(凭证/路径护栏)、测试覆盖必须被评审人确认。
- 任何修改 OpenCode 原生文件访问权限、`PermissionV1` 或 `ToolRegistry` 的代码必须被至少 2 位评审人确认。

## 集成测试优先

- 新工具/新接口:必须有对应的 `tests/integration/` 测试,用 staging 凭证跑。
- 单测**仅**用于纯函数/解析器/限流算法。
- 验收要真:每个 PR 至少 1 张 staging 跑通的截图或日志。

## 验证命令

PR 提交前必须在本地运行以下命令：

```bash
# 1. 验证上游基线（仅首次或上游变更后）
bun run verify:upstream

# 2. 代码检查
bun run lint

# 3. 类型检查（各包独立运行）
bun run --cwd packages/dataworks-core typecheck
bun run --cwd packages/opencode typecheck
bun run --cwd packages/app typecheck

# 4. 单元测试（从包目录运行，不从根目录）
bun test --cwd packages/dataworks-core ./test

# 5. 集成测试（dry-run 模式，无需云凭证）
DATAWORKS_AGENT_DRY_RUN=1 bun test ./tests/integration/dry-run
```

## 安全红线

- 严禁提交运行目录内的 `secrets.dat`、凭据库导出、阿里云 AK/SK、LLM API Key 或 MCP Token。`.keyring` 规则仅作误创建文件的兜底;生产密钥必须位于系统凭据库。
- 严禁前端代码接收未脱敏的凭证。
- 严禁 Coding 工具默认放行 SSH/AWS/凭证目录读写。