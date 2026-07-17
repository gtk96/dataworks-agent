## Summary

- 删除 `tests/unit/`（105个文件）、`tests/smoke/`、`tests/evaluation/`，仅保留 `tests/integration/` 作为唯一验证手段
- 删除 `frontend/e2e/`（19个 Playwright spec + fake server）
- 清理垃圾目录：`.agnes/`、`.codex-logs/`、`.kiro/`、`.mimocode/`、`.idea/`、`tmp/`、`logs/`、`log/`、`giikin_dw_agent/`
- 删除临时文件：`tmp_*.json`、`replace-expressions.txt`、`data/_test_tmp*`
- 更新 `pyproject.toml` testpaths 指向 `tests/integration/`
- 更新 CI 工作流：`backend.yml` 只跑集成测试，`frontend.yml` 移除 vitest，删除 `e2e.yml`
- 更新 `.gitignore` 防止垃圾文件再次入库
- 更新 README/AGENTS.md/CLAUDE.md/PROJECT_TASKS.md 中的测试命令和统计

## Changes

| 类别 | 变更 |
|---|---|
| 删除单元测试 | `tests/unit/` 105 个文件 |
| 删除冒烟测试 | `tests/smoke/` |
| 删除评测数据 | `tests/evaluation/` |
| 删除 E2E 测试 | `frontend/e2e/` 19 个 spec + fake server |
| 删除前端测试配置 | `playwright.config.ts`、`vitest.config.ts`、`test_*.py` |
| 删除 CI 工作流 | `.github/workflows/e2e.yml` |
| 删除垃圾目录 | `.agnes/`、`.codex-logs/`、`.kiro/`、`.mimocode/`、`.idea/`、`tmp/`、`logs/`、`log/`、`giikin_dw_agent/` |
| 修改配置 | `pyproject.toml` testpaths -> `["tests/integration"]` |
| 修改 CI | `backend.yml` 只跑集成测试，`frontend.yml` 移除 vitest |
| 更新文档 | README/AGENTS.md/CLAUDE.md/PROJECT_TASKS.md |

**统计**：155 files changed, 16 insertions(+), 19,027 deletions(-)
