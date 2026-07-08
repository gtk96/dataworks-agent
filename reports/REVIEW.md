# 项目复审报告 — v9 — B1-B3 / I1-I5 / cache epoch / engine publish / ods_di lookback / e2e 接入

- **日期**：2026-07-08
- **基线**：HEAD `df61337`(v9 全量,12 个实质 commit)
- **范围**:v8 之后 12 commit 增量 + 全仓补漏(覆盖率 5 维 × 资深角度);对抗验证:同根因合并、多维交叉证伪
- **轮次约定**:本文件每轮评审清空后回写(按 `memory/review-doc-overwrite-policy.md`)
- **CI 基线对照**:`reports/junit.xml`(v8 时 100 passed / 0 fail)→ v9 现 **850 run / 5 fail**(已逐 test 复现,见 §2.1)

---

## 1. v9 实质性修复总账

| commit | 主题 | 关键文件 | 评审结论 |
|---|---|---|---|
| `5abd00d` | fix(security): B1 路径遍历 + B2 MCP 绕过 guard + B3 表名注入 | `routers/import_sql.py:200-220` `_resolve_import_root`、`mcp/operations.py:21-35` `execute_ddl` guard、`modeling/sync_engine.py:14-22` `_IDENTIFIER_RE` | B1 修复本身闭环,但**白名单未把 `tests/integration/fixtures/sample_sql` 纳入**,导致 5 个集成测试 fail(见 §2.1)。B2 在 `mcp/operations.py:execute_ddl/submit_query` 闭环,但**节点域 `delete_node/offline` 完全不经过 `guard_node_op`**(见 §3.1)。B3 修复 `_IDENTIFIER_RE` 在 `sync_engine.py:14` **复制了一份**,而 `schemas.py:15` 已有,未统一引用;`init_workflow.run_with_initialization` **完全没用 `_IDENTIFIER_RE` 校验 `target_table`**(见 §3.2) |
| `611cc35` | fix(cache): epoch-based stale-write 防护 | `cache/manager.py:64-141` `_epochs`、`peek_invalidation_epoch`、`set(min_epoch=)` | 设计合理。**但 `get_or_set` helper 完全没走 epoch 路径**(见 §4.1);且 epoch 校验失败时只 return False,无 log(可观测性缺口,§5.4) |
| `425fe61` | fix(settings): S1 本机 `/api/cookie/copy` 端点 + S2 `scan-uuids` 本机白名单 | `routers/cookie.py:92-100,157-194` | **S1/S2 修复有 critical 漏洞**:`_require_local` 依赖 `client_ip` 而 `client_ip` 来自可伪造的 `X-Forwarded-For`(§3.3),无 audit log(§3.4) |
| `0a52c6d` | fix(dashboard): engine 状态写入 publish TASK_STATUS_CHANGED | `modeling/engine.py:28-49` `_publish_task_status` | publish 链路上线 8 处调用点;**但 publish 失败仅 `logger.debug`,线上不可见**(§5.1) |
| `7462a10` | fix: T1-T7(任务列表缓存失效、取消终态、重试、代理 IP、分页) | `routers/modeling.py:30-264` `_invalidate_tasks_cache` / `cancel_task` / `retry_task`、`middleware/ip_isolation.py` | T1+T3 修复有**缺口**:engine 内部 transition(DDL_GEN→TABLE_CRE 等)不通过 `_invalidate_tasks_cache`,只有 create/cancel/retry 手动调,导致 `tasks:{ip}:...` 列表缓存最多陈旧 30s(§4.2)。T4 反代部署下 IP 隔离失效(§3.3) |
| `878464a` | fix(import): 移除调度 UI,明确本页仅建表 | `frontend/src/pages/ImportSql.vue:67-95`、`routers/import_sql.py:25-26` 仍保留 `schedule_cycle/schedule_hour` 字段 | 前端清理完整;**但后端 `ImportRequest.schedule_cycle/schedule_hour` 字段已无调用方**,构成 dead code(§6.1);同时 **`import-sql.spec.ts` 仍断言已删除的"已生成调度配置"卡片 + cron 文本,df61337 接入 e2e CI 100% 红**(§3.5) |
| `5a07da` | fix(import): I3 DDL 贪婪解析 + I5 层识别 + I4 移除冗余禁用 | `routers/import_sql.py:47-143` | I3 修复按括号深度计数规避 PARTITIONED BY 误吞,**但 `in_str` 仅追踪单引号,无法识别字符串内的转义分号与双引号定界符**(§4.3);I5 层识别仅按表名小写前缀,未读取文件路径/注释源(§4.4) |
| `d66238d` | fix(ods_di): 尊重自定义 target_table + 首跑 lookback 兜底 | `services/ods_di/init_workflow.py:264-457` `run_with_initialization`、`di_config.py:265-285` `build_first_incremental_where_clause` | **target_table 入参无 `_IDENTIFIER_RE` 校验,B3 修复同源债未闭环**(§3.2);lookback `update_node` 失败后仍 `deploy_nodes` 把未改写 lookback 的节点发布上线,数据漏采无回滚(§4.5);tests/integration/fixtures/sample_sql 引入但未在 B1 白名单内,5 个测试 fail(§2.1) |
| `df61337` | ci(e2e): 修复 vite/playwright 端口矛盾并接入 e2e + vue-tsc | `frontend/vite.config.ts:13-25`、`frontend/playwright.config.ts:31-48`、`.github/workflows/test.yml:90-120` | 端口矛盾修复正确;`reuseExistingServer=true` 在开发者手开 `npm run dev` 时会复用旧 vite 而新 vite 无 `VITE_PROXY_TARGET`,e2e 静默打到真后端(§6.2);CI 没缓存 `~/.cache/ms-playwright` 每次重装(§6.3) |

---

## 2. 阻塞 CI / 集成的 critical 债

### 2.1 [critical] v9 集成测试 5 fail,根因是 B1 + I1-I5 修复未协调白名单 — **已独立复现**

**文件**:`tests/integration/test_import_sync_api.py:33-100` × 5 个测试

**复现命令**:`uv run pytest tests/integration/test_import_sync_api.py -q` → `5 failed, 7 passed in 9.09s`

**5 个 fail 全部为 400 Bad Request**:
- `test_import_preview_nonexistent_path` 期望 404,实 400
- `test_import_preview_real_path` 期望 200,实 400
- `test_import_preview_filter_ods` 期望 200,实 400
- `test_import_preview_filter_dim` 期望 200,实 400
- `test_import_import_dry_run` 期望 in (200, 422, 500, 503),实 400

**根因**:
- `53a07da` 把 `tests/integration/test_import_sync_api.py` 的 `path` 参数从硬编码 `E:/dw-modeling-template/sql/order-fulfillment` 改为相对路径 `tests/integration/fixtures/sample_sql`(`FIXTURE_SQL_DIR = str(Path(__file__).parent / "fixtures" / "sample_sql")`)
- `5abd00d` 的 B1 修复 `_resolve_import_root` 只放行 `settings.import_allowed_roots`(默认空)或 `settings.sql_template_root = "E:/dw-modeling-template/sql"` 之下的路径
- `tests/integration/fixtures/sample_sql` 不在白名单内 → 400 拒 → 5 个测试全 fail

**两个 commit 顺序**:5abd00d 先合,53a07da 后合。后者改用 fixture 路径但未把 fixture 路径加入白名单或让 B1 例外。

**影响**:`reports/junit.xml` 已 tracked 进 git(850 tests / 5 fail 的 stale 状态),df61337 接入的 e2e job 跑完会再叠加**前端 `import-sql.spec.ts` 断言已删除 UI 的 1 fail**(§3.5),CI 必红。

**修复方向**(不应用,仅作评审输出):
- 方案 A(推荐):在 `settings.import_allowed_roots` 默认值加 `["<repo>/tests/integration/fixtures/sample_sql"]`(通过 `pathlib.Path(__file__).parent.parent` 解析);或者
- 方案 B:在 conftest.py 给集成测试 patch `settings.sql_template_root` 指向 fixture 路径;或者
- 方案 C:让 `_resolve_import_root` 在测试环境(CI 标志)放行 fixture 路径

### 2.2 [critical] X-Forwarded-For 伪造 → /api/cookie/copy 与 /scan-uuids 远程凭据泄露

**文件**:
- `dataworks_agent/middleware/ip_isolation.py:33-42`(直连 peer 是 loopback 时取 XFF 最左值,无受信代理白名单)
- `dataworks_agent/routers/cookie.py:92-100,157-194`(`_require_local` 仅检查可被伪造的 `client_ip`)

**攻击链路**:
1. 反向代理(nginx)与应用同机,直连 peer = 127.0.0.1
2. 远程攻击者发 `X-Forwarded-For: 127.0.0.1` → 中间件见 peer=loopback,信任该头,取最左值 127.0.0.1
3. `request.state.client_ip = "127.0.0.1"` → `_require_local` 通过
4. `GET /api/cookie/copy` 返回 DataWorks 完整明文 Cookie
5. 同样链路可触发 `GET /api/cookie/scan-uuids` 抓 BFF 15s 内所有 URL/POST body

**多维交叉**:安全维度评审(critical)+ 并发维度评审(medium)都命中;**严重性升级为 critical**(有具体攻击路径,不只是"反代部署下会失效")。

**修复方向**:
- `ip_isolation.py`:用 `starlette.middleware.proxy_headers.ProxyHeadersMiddleware` 替代自写,配置 `trusted_hosts=settings.trusted_proxies`;绑定到 `0.0.0.0` 但 `trusted_proxies` 为空时启动期 WARNING
- `cookie.py:copy/scan-uuids`:Unix domain socket 部署(完全无 IP 层)或叠加 Admin Token(同 `/full`)

### 2.3 [critical] S1 修复(`/api/cookie/copy` 明文返回 Cookie)与 S2(`/scan-uuids`)无 audit log

**文件**:`dataworks_agent/routers/cookie.py:92-100,157-194`

**多维交叉**:
- 安全维度评审(critical):凭据泄露 + 无审计
- 可观测性维度评审(high):任何 4xx/5xx/成功都不记 audit

**复现场景**:`save_cookie_endpoint`(cookie.py:46-48)有 `audit_log("cookie_save", ip=client_ip, length=...)`,但 `auto-fetch / wait-login / copy / full / scan-uuids` 全部缺 audit。本机被远控或恶意脚本读到 `/api/cookie/copy` 时,凭据泄露但 audit log 空白。

**修复方向**:`_require_local` 路径上加 `audit_log("cookie_copy"|"cookie_full"|"cookie_scan_uuids", ip=client_ip, length=len(cookie) if copy)`;与 `save_cookie_endpoint` 写法对齐。

---

## 3. v9 修复链上的 high 债

### 3.1 [high] B2 修复未覆盖节点域 `delete_node/offline/undeploy`

**文件**:`dataworks_agent/api_clients/destructive_guard.py:102-110` `guard_node_op`(函数存在但**无任何生产路径调用**)

**多维交叉**:安全维度评审(high)独立命中。

**复现场景**:`scripts/delete_dwd_nodes.py` 与未来 `delete_node/offline` 提交点完全不经过 `guard_node_op`,B2 修复"所有破坏性操作同一拦截器覆盖"目标对节点域落空。grep 验证:整个 `dataworks_agent/` 树无 `guard_node_op(` 调用。

**修复方向**:在 `api_clients/openapi_client.py` 与 `api_clients/bff_client.py` 的 `delete_node / offline / undeploy` 提交点统一加 `guard_node_op(op_name)`,并加测试断言被调用。

### 3.2 [high] B3 修复同源债:target_table 入参在 `init_workflow`/`DIPipeline.run` 未走 `_IDENTIFIER_RE`

**文件**:
- `dataworks_agent/services/ods_di/init_workflow.py:284-286` `run_with_initialization(target_table=None)`
- `dataworks_agent/services/ods_di/pipeline.py:40-50` `DIPipeline.run(target_table=None)`

**多维交叉**:数据维度评审(high)独立命中。

**复现**:`d66238d` 让 `target_table` 接受用户传入(尊重自定义),但**未做 B3 同款 `^[A-Za-z_][A-Za-z0-9_]*$` 校验**。`generate_node_path(script_path, ods_table)` 直接 f-string 拼成 `dataworks_agent/01_ODS/<target_table>`,`build_node_name(ods_table, ...)` 同理。`create_di_node` 把含分号/路径分隔符的名字原样写进 DataWorks。

**修复方向**:在 `run_with_initialization` 与 `DIPipeline.run` 入口首行调用 `from dataworks_agent.modeling.sync_engine import _assert_safe_table_name; _assert_safe_table_name(target_table)`;并把 `_IDENTIFIER_RE` 从 `sync_engine.py:14` 移除(已有 `schemas.py:15` 副本),改 import 统一。

### 3.3 [high] `ip_isolation.py:39` 信任边界 = "direct peer in loopback set" 在生产反代下塌缩为单一 UserContext

**文件**:`dataworks_agent/middleware/ip_isolation.py:33-54`

**多维交叉**:安全维度评审(critical)+ 并发维度评审(medium)同根因。

**复现场景**:进程 bind 到 `0.0.0.0:8000`,nginx `10.0.0.1` 前置 → uvicorn 直连 peer = `10.0.0.1`,**不在 loopback set** → 中间件忽略 `X-Forwarded-For`,所有用户塌缩到 `UserContext(ip="10.0.0.1")`,各自 `active_tasks/cookie/task_queue` 共享 — 跨用户状态污染。

**修复方向**:用 `starlette.middleware.proxy_headers.ProxyHeadersMiddleware`,`trusted_hosts=settings.trusted_proxies`(白名单配置);bind 到非 loopback 但 `trusted_proxies` 为空时启动期 `logger.warning`;接受 first untrusted hop AS-IS。

### 3.4 [high] S1/S2 修复有 IP 鉴权可绕过但缺 audit log(同 §2.3 critical 撞点)

已在 §2.3 整合。

### 3.5 [high] `import-sql.spec.ts:32-39` 仍断言已删除的"已生成调度配置"卡片 + cron 文本 — **已独立复现**

**文件**:`frontend/e2e/import-sql.spec.ts:23-39`(全文已 Read)

**证据**:
```ts
test('ImportSql 调度配置摘要 — 默认非 none 调度应出现', async ({ page }) => {
  await page.goto('/import')
  await page.getByRole('button', { name: '预览' }).click()
  await expect(page.getByText('dim_ord_ofc_cancel_reason_all').first()).toBeVisible({ timeout: 10000 })
  // 调度摘要卡片应出现
  await expect(page.getByText('已生成调度配置')).toBeVisible()
  // 调度 cron 应展示 (00 01 03 * * ? 形式)
  await expect(page.locator('body')).toContainText('00 01')
})
```

**多维交叉**:前端维度评审(high)+ 主线程新发现(独立复现)。

**根因**:`ImportSql.vue:878464a` 已删除 `buildSchedule()` 函数、`scheduleConfigs` ref、调度摘要 el-card、cron 列;`import-sql.spec.ts` 未同步更新;df61337 接入的 e2e CI 100% 红。

**修复方向**:重写或删除 `import-sql.spec.ts` 的第二个 case,改断言为"ImportSql 不再展示调度 UI"(如 `expect(page.locator('body')).not.toContainText('已生成调度配置')`),与 `878464a` 的"本页仅建表"语义对齐。

### 3.6 [high] `docs/REVIEW.md` 是 v16 评审档(基线 1a16818,filter-repo 改写后该 SHA 不存在)+ `readme_decoded.md` 是 aliyun 官方仓库 README 副本

**文件**:
- `reports/REVIEW.md` 引用 `1a16818` commit(filter-repo 改写后失效)
- `readme_decoded.md`(7K)内容是 alibabacloud-dataworks-mcp-server 官方 README,与本项目无关

**多维交叉**:可观测性维度评审(high × 2)命中。

**根因**:
- `REVIEW.md` 9d19277..HEAD 范围未触动(本轮评审未覆盖),v9 修复(B1-B3 / cache epoch / engine publish / ods_di lookback / e2e)未在评审档反映
- `readme_decoded.md` 名字含"decoded"暗示是某次 Base64 解码产物误入仓库根;若按其跑 `npm install alibabacloud-dataworks-mcp-server` 会装错包

**修复方向**:
- 本评审档**已落地**(见本文件,覆盖 v16 → v9)
- `git rm readme_decoded.md` + `.gitignore` 加 `*decoded.md`;若属外部调研参考应放 `reports/` 或 `docs/` 子目录

---

## 4. v9 范围状态机 / 缓存 / 解析债

### 4.1 [medium] `CacheManager.get_or_set` 缺 epoch 防护 — R18 修复的同款 race

**文件**:`dataworks_agent/cache/manager.py:173-186`

**复现**:`get_or_set(key, factory, ttl)` 调 `self.get(key)` 然后 `self.set(key, value, ttl)`,**不传 `min_epoch=`**。任何调用 `get_or_set` 跨慢 factory 的代码都会暴露 R18 已修复的 race。

**多维交叉**:并发维度评审(medium)命中。

**修复方向**:加 `epoch_token` 参数(peek inside then set with min_epoch);或 docstring 显式 caveat 指 peek/set pattern。

### 4.2 [medium] T1+T3 修复有缺口:engine 内部 transition 不触发 `_invalidate_tasks_cache`

**文件**:`dataworks_agent/routers/monitor.py:135-143` `_broadcast_task_status`

**复现场景**:engine 在 DDL_GEN→TABLE_CRE→ROOT_CHECK→DML_WRITE→SCHED_CFG→COMPLETED 共 6 次内部 transition 都 publish `TASK_STATUS_CHANGED`,但 `_broadcast_task_status` 只 `delete("dashboard")`,**没有 `invalidate_by_source("tasks")`**。`tasks:{client_ip}:...` 列表缓存(modeling.py:115)的失效完全靠 create/cancel/retry 手动调,导致 engine 内部 transition 后列表最多陈旧 30s。

**多维交叉**:并发维度评审(high)独立命中。

**修复方向**:`monitor.py:_broadcast_task_status` 加 `get_cache_manager().invalidate_by_source("tasks")`;测试镜像 `test_dashboard_cache.py:103`。

### 4.3 [medium] DDL 贪婪解析 `in_str` 仅追踪单引号,无法处理转义分号与双引号定界

**文件**:`dataworks_agent/routers/import_sql.py:84-99`

**多维交叉**:数据维度评审(medium)命中。

**复现场景**:`DEFAULT ');\nNEXT'` 字符串内含分号,`in_str` 切换到 false 时遇 `)` 直接 `depth=0` 截断;PARTITIONED BY 被吞。生产 DDL 极少在 default 写分号但保留风险面。

**修复方向**:把单字符 `in_str` 替换为五态 tokenizer(single-quoted / double-quoted-identifier / line-comment / block-comment / normal),遇 `'` 且下一字符是 `'`(SQL 标准双单引号转义)不切换。

### 4.4 [medium] I5 层识别仅按表名小写前缀,未读取文件路径/注释源

**文件**:`dataworks_agent/routers/import_sql.py:117-124`

**复现场景**:`-- layer: dim` 注释但表名 `ods_user_profile` → 判为 ODS,与运维意图不符;反之命名规范错配也修不了。

**多维交叉**:数据维度评审(low)命中。

**修复方向**:在 strip 后、layer 推断前扫 stmt 顶部 5 行内 `-- layer: (ods|dwd|dim|dws)`,命中且与前缀冲突时以注释为准并 `logger.warning`。

### 4.5 [medium] ods_di lookback 失败仍 `deploy_nodes` 发布未改写 lookback 的节点 — 数据漏采无回滚

**文件**:`dataworks_agent/services/ods_di/init_workflow.py:441-455`

**多维交叉**:数据维度评审(medium)命中。

**复现场景**:`update_node` 失败(网络瞬断)→ `result["incremental"]["first_run_lookback"]["status"]="failed"` → 继续 `deploy_nodes(incr_uuid)` 把未改写 lookback 的节点发布上线 → 首次调度按标准增量窗口跑,init 与首跑之间数据漏采,无回滚路径。

**修复方向**:把 `update_node` 失败改为 fail-closed(`result["success"]=False`,跳过 `deploy_nodes` 与 publish_gate 失败分支行为一致)。

---

## 5. v9 可观测性债(覆盖 publish 链路 + audit + 日志)

### 5.1 [high] `engine._publish_task_status` 失败仅 `logger.debug` + 整个项目无 `request_id` 串联

**文件**:
- `dataworks_agent/modeling/engine.py:28-49`
- `dataworks_agent/routers/modeling.py:41-56`

**多维交叉**:可观测性维度评审(high × 2)命中。

**复现场景**:R17/R18 修复后驱动 dashboard 的关键 publish 通道(8 处调用),失败时只 `logger.debug`,线上 dashboard 看不到状态变更时无告警;排查"为什么前端没刷新"无法关联 task_id 找到 publish 失败原因。

**修复方向**:`logger.warning('TASK_STATUS_CHANGED publish failed: task=%s status=%s err=%s')`;`event.data` 加 `request_id`(`uuid4()`),WS broadcast 与 cache delete 透传到 logger;CLAUDE.md §9 加 request_id 串联规则。

### 5.2 [high] `_broadcast_task_status` 静默吞 `cache.delete` 与 `send_text` 异常

**文件**:`dataworks_agent/routers/monitor.py:135-166`

**多维交叉**:可观测性维度评审(high)命中。

**复现场景**:`except Exception: dead.append(ws)` 静默踢出死连接,无 `logger.debug`;`get_cache_manager().delete("dashboard")` 失败完全无 catch。dashboard "实时刷新名存实亡" 时无可观测信号。

**修复方向**:`try/except` 包 `cache.delete` 加 `logger.warning`;`dead.append` 前 `logger.debug` 报踢出比例;`publish_async` 失败升级到 `logger.warning`。

### 5.3 [medium] `import_sql.py` 仍保留 `ImportRequest.schedule_cycle/schedule_hour` 字段(已无前端调用方)

**文件**:`dataworks_agent/routers/import_sql.py:25-26` `class ImportRequest`

**多维交叉**:主线程新发现(独立验证)。

**复现场景**:`878464a` 删了 `ImportSql.vue` 的 `schedule ref` 与 `buildSchedule()`,但后端 `ImportRequest.schedule_cycle: str = ""` 与 `schedule_hour: int = 3` 字段未同步删除,构成 dead code;`doImport` 也不传这俩字段,后端永远收到默认值。

**修复方向**:删 `schedule_cycle / schedule_hour` 字段(或保留 + 标 deprecated 等下版移除)。

### 5.4 [medium] `CacheManager.set(min_epoch=)` 校验失败时无 stale-write 计数

**文件**:`dataworks_agent/cache/manager.py:117-141`

**多维交叉**:可观测性维度评审(low)命中。

**复现场景**:`return False` 不写,调用方(/dashboard handler)拿 False 也只 return result,无 logger 记录 stale-write 丢弃次数。线上 1 分钟可能数十次 stale-write 全部不可见,无法判断 cache TTL / publish 频率 / 真并发竞争。

**修复方向**:`self._stale_writes = self._stale_writes + 1`,`get_stats()` 暴露计数;周期 logger.info 报告。

### 5.5 [medium] CLAUDE.md §5/§6 文档漂移:v9 5 个新修复未记录

**文件**:`CLAUDE.md:188`(§5-§7)

**多维交叉**:可观测性维度评审(medium)命中。

**复现场景**:v9 引入的 R18 cache epoch 机制、engine publish 链路、S1/S2 cookie copy 端点设计、B1-B3 修复设计原则未在 §5/§6 段落记录。下次维护者按 CLAUDE.md 找不到 "engine publish" 入口或"cache epoch 校验模式",会重新发明轮子。

**修复方向**:§7.9 加 R18 epoch-based stale-write 防护;§7.10 加 R17 engine publish 链路;§5 加 B1/B2/B3 修复概要。

---

## 6. v9 范围外但本次评审顺带发现的项目级债

### 6.1 [medium] `cookie_encryption_key` 默认值 = `""`,`.env` 未设置 → Fernet 在空 key 下派生

**文件**:`dataworks_agent/config.py:75` `cookie_encryption_key: str = ""`

**根因**:S1/S2 修复关注 cookie 鉴权访问面,但**加密本身的根密钥空**:
- `_get_fernet()`(`cookie/crypto.py:43-54`)用 `raw_key = settings.cookie_encryption_key.encode("utf-8")` 派生
- 空字符串 + per-install salt + 600k 迭代 → 派生路径确定(只要 salt 相同即解密)
- `os.chmod(COOKIE_FILE, 0o600)` 在 Windows 上被 `suppress(OSError)` 吞掉

**多维交叉**:主线程新发现(独立验证 `.env` 文件,确认 `COOKIE_ENCRYPTION_KEY` 行缺失)。

**修复方向**:`cookie_encryption_key: str = Field(min_length=16)` 强制非空;启动期 `pydantic_validator` 校验;Windows 上 `chmod` 失败时 `logger.error` 而非 silent。

### 6.2 [medium] `import_sql.py` 写端点(`/import`, `/deploy`)未用 `require_write_access`

**文件**:`dataworks_agent/routers/import_sql.py:245-323,408-453`

**多维交叉**:安全维度评审(high)+ 主线程新发现(独立 grep 验证)。

**根因**:`require_write_access` 在 `schemas.py:18-25` 定义,被 `sync.py:71` 与 `reconciliation.py:24` 通过 `Depends` 引用,但 `import_sql.py` 写端点(/import、/deploy)无任何写权限闸。`/import` 经 `MCP.execute_ddl` 建表,`/deploy` 经 BFF/OpenAPI 建节点配调度发布,任一可达客户端可触发。

**修复方向**:`/import` 与 `/deploy` 端点加 `_auth=Depends(require_write_access)`;与 sync/reconciliation 写端点对齐。

### 6.3 [medium] vite `reuseExistingServer=true` + 开发者手开 `npm run dev` → e2e 静默打到真后端

**文件**:`frontend/playwright.config.ts:31-48`、`frontend/vite.config.ts:13-25`

**多维交叉**:前端维度评审(low)命中。

**复现场景**:`reuseExistingServer: true` 同时打开 fake-server:8086 + vite:3000;若开发者手开 `npm run dev` 占着 3000,playwright 复用旧 vite,而旧 vite 进程**没有 `VITE_PROXY_TARGET`**,会回退到 8085 真后端,所有 mock 端点失效,POST `/api/sync/diff` 触达真后端(可能落库或 404),e2e 看似通过(因真后端 200)但已不再隔离。

**修复方向**:`vite.config.ts` 直接判断 `process.env.PLAYWRIGHT === '1'` 强制切到 8086;或 `playwright.config.ts` 加 `globalSetup` 把 `VITE_PROXY_TARGET` 写到临时 `.env` 再 spawn vite;或去掉 `reuseExistingServer` 让 CI 一致。

### 6.4 [medium] `reports/junit.xml` 被 tracked 进 git,stale 5 fail 误导 reviewer — **已独立验证**

**文件**:`reports/junit.xml`(git ls-files 包含)

**多维交叉**:前端维度评审(low)+ 主线程新发现(独立验证 `git ls-files reports/` 含 junit.xml)。

**根因**:v8 时 100 tests / 0 fail → v9 现 850 / 5 fail,`reports/junit.xml` 是 v9 跑出的产物但已 tracked,v9 评审档说"pytest 全过"会误导。`.gitignore` 未排 `*.xml` 与 `reports/*.xml`。

**修复方向**:`git rm --cached reports/junit.xml` + `.gitignore` 加 `reports/*.xml`;同步修 5 个 fail(§2.1)。

### 6.5 [low] `cookie.py` Admin Token 截断至 64 位 + `!=` 明文比较 + 经 query 传

**文件**:`dataworks_agent/routers/cookie.py:26-36,80-89`

**多维交叉**:安全维度评审(medium)命中。

**复现场景**:`hmac.new(...).hexdigest()[:16]` 16 hex = 64 bit → 降低暴力成本;`token != expected` 存在时序侧信道;`?token=` query 参数落入访问日志/浏览器历史/Referer 泄露。

**修复方向**:`hmac.compare_digest` 恒定时间比较;保留全长摘要(256 bit);改 `X-Admin-Token` 请求头而非 query。

### 6.6 [low] `mcp/operations.py:count_table` 直接 f-string 拼 SELECT,无标识符校验

**文件**:`dataworks_agent/mcp/operations.py:93-99`

**多维交叉**:安全维度评审(low)命中。

**复现场景**:`sql = f"SELECT COUNT(*) AS cnt FROM {table_full_name}"` → `submit_query` → `guard_sql` 只拦破坏性关键字不防注入。当前无生产调用点但为已暴露注入面。

**修复方向**:`table_full_name` 施加与 B3 同款 `^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$` 校验后再拼接。

### 6.7 [low] `pre-commit-config.yaml` 只配 ruff,不跑 pytest、不拦截敏感文件

**文件**:`E:\giikin_dw_agent\.pre-commit-config.yaml`

**多维交叉**:可观测性维度评审(low)命中。

**复现场景**:CLAUDE.md §8 要求 "CI 回归门无异常:uv run ruff check . + 全量 pytest",但 pre-commit 完全不跑测试;`readme_decoded.md` 因无 large-file / sensitive-file 钩子,原样入库。

**修复方向**:加 local hook 跑 `uv run pytest tests/unit -q -x`(5 秒门禁);加 gitleaks 钩子拦截敏感文件。

### 6.8 [low] `sync_engine._generate_alter_sql` 把列名/类型原样拼进 ALTER,B3 校验未覆盖字段标识符

**文件**:`dataworks_agent/modeling/sync_engine.py:172-184`

**多维交叉**:安全维度评审(low)命中。

**复现场景**:dev/prod DDL 文本被污染时,`d['name']/d['dtype']/d['new_type']` 直接拼进 ALTER TABLE,字段级标识符无 `_IDENTIFIER_RE` 校验。

**修复方向**:对 diff 中的 `name` 用 `_IDENTIFIER_RE`,`dtype`/`new_type` 走白名单类型集合校验后拼接。

---

## 7. v9 验证矩阵

| 检查 | 结果 | 备注 |
|---|---|---|
| pytest 全量 | **850 / 5 fail**(已复现) | v9 引入 5 个 fail,见 §2.1 |
| E2E(import-sql.spec.ts) | **必红**(未跑) | 见 §3.5 |
| ruff / vue-tsc | 0 错误 | v8 baseline 一致 |
| v9 新增单测 | 5 个文件,共 ~700 行 | `test_cache_invalidation`(165)+`test_dashboard_cache`(209)+`test_engine_publish`(182)+`test_ods_di_init`(123)+`test_ods_di_config`(17 新增) |
| v8→v9 评审档闭环 | v8 36 条已闭环 | 见 §1 v9 总账 |

---

## 8. v9 评审闭环总账

| 维度 | finding 数 | 已去重/合并后 | 关键观察 |
|---|---|---|---|
| 安全/鉴权 | 9(2 critical / 2 high / 2 medium / 3 low) | 8 进报告 | critical 2 条全进,§2.2 + §2.3 |
| 数据/导入 | 9(2 high / 4 medium / 3 low) | 5 进报告 | §3.2 high + §4.3/4.4/4.5 medium + §6.6 low |
| 并发/状态机/缓存 | 8(1 high / 4 medium / 2 low / 1 info) | 5 进报告 | §3.5 high + §4.1/4.2/4.5 medium |
| 前端/e2e | 15(1 high / 4 medium / 3 low + 5 info) | 3 进报告 | §3.5 high + §6.3/6.4 medium |
| 可观测性/性能/可测试性/文档 | 18(4 high / 6 medium / 5 low / 3 info) | 5 进报告 | §5.1/5.2 high + §5.3/5.4/5.5 medium |
| 主线程独立新发现(交叉验证后) | 14 条 | 6 进报告 | §2.1 critical + §3.2/3.5 整合 + §6.1/6.2/6.4 medium |

**总 finding 数**:~49 条原始 → 19 条进报告(critical 3、high 6、medium 8、low 2)

---

## 9. 关键 takeaway

1. **v9 三个 critical 撞点都不是"独立缺陷",而是"v8 范围修复 + v9 范围新功能"未协调**:
   - §2.1:B1 白名单 + I1-I5 fixture 路径 → 5 测试 fail
   - §2.2 + §3.3:S1/S2 鉴权 + T4 IP 隔离 → XFF 伪造链路
   - §2.3:cookie copy 端点 + 缺 audit log → 凭据泄露无溯源
2. **CLAUDE.md §2 简单优先与 §8 修改后必测试的张力**:v9 修复多走"小改动 + 加测试",但**测试本身存在未协调债**(测试改路径未把路径加入白名单 / 测试断言已删除 UI)
3. **B1/B2/B3 三件套修复**在 `mcp/operations.py:execute_ddl/submit_query` 与 `sync_engine._IDENTIFIER_RE` 闭环,但**节点域与 `init_workflow` 的同款 B3 校验未延伸**,`_IDENTIFIER_RE` 在 `schemas.py:15` 与 `sync_engine.py:14` 重复定义 — 应统一
4. **R17/R18 修复的 publish 链路**设计上正确,但**失败不可观测**(仅 `logger.debug`)+ **T1+T3 列表缓存失效有缺口**(engine 内部 transition 不触发) + **fire-and-forget 与 engine 不一致**
5. **跨范围债**:`cookie_encryption_key` 默认空(S1/S2 修复本应顺手补)、`require_write_access` 在 import_sql 写端点缺(S1/B1 修复本应顺手加)、`readme_decoded.md` 误入(无 git 钩子拦截)
6. **CI 现状**:pytest 850 / 5 fail + e2e 1 fail(`import-sql.spec.ts`)→ 6 个红,需要 df61337 紧跟 PR 修 fixture 路径白名单 + 删 stale spec 断言

**下一个候选**(v10):
- §2.1 fixture 路径白名单(立即阻塞 CI,high pri)
- §3.5 删 import-sql.spec.ts 第二个 case(立即阻塞 CI,high pri)
- §2.2 + §2.3 XFF 伪造 + audit log(critical,low cost)
- §3.2 B3 修复同源债(target_table 校验 + `_IDENTIFIER_RE` 统一引用)
- §3.3 + §3.4 ip_isolation 重构为 ProxyHeadersMiddleware + cookie copy 端点补 audit log
- §4.1 + §4.2 cache `get_or_set` epoch + monitor publish 链路补列表缓存失效
- §6.1 + §6.2 cookie 加密密钥强制 + import_sql 写端点补 require_write_access
