# 项目复审报告 — v10 — v9 候选债闭环 + CI 修复

- **日期**：2026-07-08
- **基线**：HEAD `74740f2`（CI 修复）→ 本轮回写覆盖 v9 候选清单
- **范围**：v9 §2–§6 候选项落地进度；不含新一轮全仓扫描
- **轮次约定**：本文件每轮评审清空后回写

---

## 1. v10 已闭环（相对 v9 候选）

| v9 条目 | commit 主题 | 结论 |
|---|---|---|
| §2.1 fixture 白名单 | `a491ee1` | 集成测试 5 fail 已修 |
| §2.2/§2.3 XFF + Cookie audit | `302c123` | `client_ip.py` TCP peer；敏感端点 audit |
| §3.1 guard_node_op 节点域 | `302c123` | BFF delete_package + OpenAPI offline |
| §3.2 target_table + `_IDENTIFIER_RE` | `8393729` + **v10** | 校验已接入；**v10 统一到 `schemas.assert_safe_table_name`** |
| §3.5 import-sql e2e | `74740f2` | 调度 UI 断言已删/改 |
| §4.1 `get_or_set` epoch | **v10** | factory 前 peek + set(min_epoch=) |
| §4.2 tasks 列表缓存 | **v10** | `_broadcast_task_status` → `invalidate_by_source("tasks")` |
| §4.5 lookback fail-closed | **v10** | update_node 失败跳过 deploy |
| §5.1 publish 失败可观测 | **v10** | `logger.warning` + `request_id` |
| §5.2 broadcast 异常日志 | **v10** | cache 失效/WS 踢连接 debug/warning |
| §5.4 stale-write 计数 | **v10** | `get_stats()["stale_writes"]` |
| §6.1 cookie 密钥 | **v10** | `Field` validator min 16；CI/conftest 注入 |
| §6.2 import 写鉴权 | `302c123` | `require_write_access` |
| §6.3 e2e reuseExistingServer | `74740f2` | CI `reuseExistingServer: !CI` + `start-vite.mjs` |
| §6.4 junit.xml tracked | `e974300` | 已 untrack |
| CI 四 workflow | `74740f2` | ruff format / vue-tsc / pre-commit / e2e selector |

---

## 2. v10 验证矩阵

| 检查 | 结果 |
|---|---|
| pytest 全量 | **869 passed** |
| E2E Playwright | **27 passed**（本地） |
| ruff check/format | 通过 |
| Backend CI env | `COOKIE_ENCRYPTION_KEY` 已写入 workflow |

---

## 3. 仍开放（未纳入 v10，留待 v11）

| 条目 | 级别 | 说明 |
|---|---|---|
| §3.3 ProxyHeadersMiddleware | high | ~~中间件仍自写~~ → **v11 已接入** `middleware/proxy_headers.py` + `TRUSTED_PROXIES` |
| §4.3 DDL 五态 tokenizer | medium | ~~单引号 in_str~~ → **v11 已改** `_find_columns_block_end` |
| §4.4 I5 层识别注释源 | medium | ~~仅表名前缀~~ → **v11 已支持** `-- layer: dim` 优先 |
| §5.3 schedule_cycle dead code | medium | ~~`ImportRequest` 遗留字段~~ → **v0.1.1 已删** |
| §5.5 CLAUDE.md 文档漂移 | medium | ~~R17/R18/B1-B3 未写入~~ → **v0.1.1 已补 §6 + §7.9/7.10** |
| §6.5 Admin Token 时序/长度 | low | compare_digest + header 传参 |
| §6.6 count_table 标识符 | low | MCP f-string |
| §6.7 pre-commit pytest hook | low | 仅 ruff |
| §6.8 alter 字段标识符 | low | sync_engine diff 列名 |

---

## 4. 关键 takeaway

1. **v9→v10 主线**：安全（XFF/audit/写鉴权/节点删除）→ 缓存一致（epoch/tasks 失效）→ 可观测（publish warning）→ CI 全绿。
2. **`assert_safe_table_name` 唯一入口在 `schemas.py`**，禁止业务模块复制 `_IDENTIFIER_RE`。
3. **ods_di lookback** 失败必须 fail-closed，与 publish_gate 语义对齐。
4. **`COOKIE_ENCRYPTION_KEY` 启动即校验**，空密钥不再 silent 派生 Fernet。

**下一个候选（v11）**：§3.3 ProxyHeadersMiddleware、§4.3/4.4 导入解析、§5.3 dead code 清理。
