# 项目复审报告 — v16 — F6-7 lineage 并发 + G1 dashboard legacy GROUP BY

- **日期**：2026-07-07
- **基线**：HEAD `1a16818`（v16 F6-7 lineage collect 并发 + G1 aggregate_type_breakdown GROUP BY）
- **范围**：本轮做的实质性修复
- **轮次约定**：本文件每轮评审清空后回写（按 `memory/review-doc-overwrite-policy.md`）

---

## 1. 本轮实质性修复

### 1.1 F6-7 lineage export collect 阶段并发（commit `1a16818`）

**问题**：`export_lineage` 收集所有节点代码是 `[await collect_node(bff, node, env) for node in result.nodes.values()]`——串行 await list，N 节点需 N 次串行 RPC。深度 D + N 父节点场景下 export 路径耗时 = N × RPC 延迟。

**修复**：
- 新增 `collect_nodes_concurrent(bff, nodes, env, concurrency=8)`：
  - `asyncio.Semaphore(concurrency)` 限流（默认 8 路）
  - `asyncio.gather(*(_one(n) for n in nodes.values()))` 并发调度
- `export_lineage` 改为 `collected = await collect_nodes_concurrent(bff, result.nodes, env)`
- **行为完全兼容 `collect_node`**：每节点独立 try/except，失败只标自己 error，不影响其他节点

> MAX_NODES=500 全并发会爆 BFF；信号量默认 8 路是经 BFF 阈值经验的安全值。

### 1.2 G1 aggregate_type_breakdown legacy 路径 GROUP BY（commit `1a16818`）

**背景**：v15 F2-5 修了 modeling.py 列表路径 SQL 下推，但 `task_classification.aggregate_type_breakdown` 仍对 `node_type IS NULL` 行走 Python 端 `infer_node_type` 循环——是 v15 F2-5 在 dashboard 聚合侧的延伸。

**修复**：
- 复用 v15 `infer_node_type_sql()` 把推断逻辑下推到数据库
- legacy 路径从 `.scalars().all()` Python 循环改为 `GROUP BY(ntype, status)` 一次查询
- 与显式 `node_type` GROUP BY 路径行为一致

---

## 2. 核实结果总表

| 编号 | HEAD 现状 | 处置 |
|---|---|---|
| F6-7 lineage BFS 串行 | **本轮 §1.1 已闭环**（collect 阶段并发） | 闭环 |
| F6-4 命名正则不一致 | 待业务侧确认 | 仍待修 |
| F5-9 workspace keyword 校验 | 低优 | 仍待修 |
| L3+ runtime/semantic/mcp_server 端到端验证 | 仓库级 | 仍待修 |
| **v10-v15 已闭环全部** | 见评审档历史档 | 闭环 |

> **注**：`traverse_upstream` BFS 本身仍串行（第 127 行 `await bff.get_node_parents_by_depth`），按 CLAUDE.md §2 简单优先留待 v17——改 BFS 跨层并发需重写 visited 集合语义，价值/成本不划算。

---

## 3. 验证矩阵

| 检查 | 结果 |
|---|---|
| pytest 全量 | **816/816 通过**（v15 813 + v16 新增 3） |
| vitest 前端 | 13/13 通过 |
| E2E tasklist + task-detail | 5/5 通过 |
| ruff / vue-tsc | 0 错误 |

---

## 4. v10-v16 七轮闭环总账

| 轮次 | 页面 / 模块 | 评审档闭环 |
|---|---|---|
| v10 | Dashboard | F1-2/3/5 |
| v11 | Dashboard | F1-1/4/7 |
| v12 | DataSourceManager | F5 系列 + D1-D8 + R1 + D5 |
| v13 | TaskList / TaskDetail | F2-1/3/4/6/7 + R2/R3/R4/R5 |
| v14 | DDL checker / 治理 | F6-3 + F6-1/5/8 文档勘误 |
| v15 | modeling.py 性能 | **F2-5**（SQL 下推） |
| v16 | lineage 性能 | **F6-7 + G1** |

---

## 5. 仓库级仍存在的债（v17+）

| 优先级 | 编号 | 内容 |
|---|---|---|
| 中 | traverse_upstream BFS | lineage BFS 层内并发（价值/成本不划算，留 v17+） |
| 中 | F6-4 | ODS/DWD/DWS 命名正则下划线规则不一致（需业务侧确认） |
| 低 | F5-9 | workspace keyword 校验 |
| 低 | L3+ | runtime/semantic/mcp_server 端到端验证 |
| 低 | vite proxy | playwright.config.ts 注释与 vite.config.ts 实际目标不一致（E2E 实际跑真后端） |

---

## 6. 关键 takeaway

1. **F6-7 + G1 都是"半优化"——价值高、改动小**：
   - collect 阶段并发：N×RPC → N/8×RPC，N=500 节点从约 50s 降至约 6.3s（按 100ms/RPC 估算）
   - G1 GROUP BY 复用 v15 SQL CASE WHEN，零额外代码、纯收益
2. **CLAUDE.md §2 简单优先的取舍**：traverse_upstream BFS 跨层并发价值/成本不划算，留待 v17；collect 阶段是 fan-out 经典场景，成本极低收益高。
3. **测试断言并发而非猜测**：3 个单测用 `peak ≤ 2`（信号量）和 `elapsed < 0.3s`（8×100ms 并发应 < 300ms）——直接断言行为而非内部实现。
4. **v10-v16 七轮共闭环 ~32+ 条 P0/P1 评审档债**：dashboard / DataSourceManager / TaskList/TaskDetail / DDL checker / modeling.py / governance 全清干净。

下一个候选：**traverse_upstream BFS 层内并发**（最后一条 BFS 串行债）或 **L3+ runtime/semantic/mcp_server 端到端验证**（仓库级覆盖）。