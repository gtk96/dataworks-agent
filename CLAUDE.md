# CLAUDE.md

这份文件约束 Claude Code 在本项目里的工作方式，用来减少常见的 AI 编程失误。你可以在此基础上继续补充项目专属规则。

参考来源：https://github.com/forrestchang/andrej-karpathy-skills/blob/main/CLAUDE.md

取舍说明：这些规则更偏向谨慎和可验证，而不是最快完成。遇到很小的简单任务时，可以按实际情况简化流程。

本文件只保留可提交的通用规则和占位符。项目名、地域、内部 endpoint、目录与真实资源标识等本地信息写入 CLAUDE.local.md；该文件必须被 .gitignore 忽略，禁止提交。

## 项目背景

开始修改前，先阅读 README、配置文件和目录结构，确认项目目标、技术栈和关键目录；不要凭经验猜。

## Git 分支与多 Agent 隔离（强制）

任何**新增功能、Bug 修复、重构或代码修改**都必须在独立分支中开发，严禁直接在 `master` 上修改代码。

开始开发前必须按以下顺序执行：

1. 运行 `git status --short`，确认当前工作区干净。发现其他 Agent 或用户留下的未提交改动时，立即停止；不得擅自 `stash`、提交、覆盖、移动或回滚这些改动。
2. 更新本地 `master`：

   ```powershell
   git fetch origin
   git switch master
   git pull --ff-only origin master
   ```

3. 必须从最新 `master` 创建本次任务的独立分支，例如：

   ```powershell
   git switch -c feat/<feature-name>
   # 或 fix/<bug-name>、refactor/<topic-name>
   ```

4. 确认当前分支不是 `master` 后，才允许修改代码。

多个 Agent 或多个会话并行开发时：

- 每个 Agent/会话必须使用**独立分支和独立 Git worktree**，禁止共享同一个工作目录进行开发。
- 为各 Agent 明确互不重叠的文件所有权，例如后端 Agent 负责 `dataworks_agent/**`，前端 Agent 负责 `frontend/**`。
- 公共 API、Schema、锁文件、配置和共享文档必须先确定唯一负责人；其他 Agent 不得同时修改。
- 不得覆盖、回滚或顺手整理其他 Agent 的修改；发现冲突时先停止并说明。
- 每个分支应保持小步提交，并在本分支完成相关测试。
- 合并前重新同步最新 `master`，解决冲突并完成前后端集成验证后，才能合入主分支。

如果无法确认当前 `master` 是否最新、工作区是否干净、改动归属或分支所有权，**不得开始编码**。
## 常用命令

只使用本项目已经声明的命令。优先从 README、`package.json` scripts、Makefile、`pyproject.toml`、`Cargo.toml`、CI 配置中确认。

不要把示例命令写成项目事实；没有确认过的命令不要写进本文件，也不要留下占位文本。

## 1. 写代码前先想清楚

不要假装已经理解，也不要把不确定性藏起来。该说清楚的地方先说清楚。

开始实现前：

- 明确写出你的假设；不确定就问。
- 如果需求存在多种理解，把几种理解列出来，不要悄悄选一个。
- 如果有更简单的做法，要主动说明。
- 该反对时要反对；发现需求不清楚，就停下来指出哪里不清楚。

**敏感数据守则（绝对红线）：**

- **严禁**把生产 `.env`（`ALIYUN_ACCESS_KEY_*`、`LLM_API_KEY`、`COOKIE_ENCRYPTION_KEY`、`DATAWORKS_PROJECT_ID/TENANT_ID`、`DATAWORKS_DATASOURCE_ID`、真实 Cookie 等）粘贴到任何 LLM 对话窗口、Issue、PR 评论、内部 wiki、日志或告警里。
- LLM 对话历史可能被服务端留档、被镜像回灌、被其他协作者看到；只要贴出明文就视为已泄漏。
- **每次看到 `.env` 内容时**先警告用户，并主动提示云控制台轮换凭据。
- 仓库内只允许 `.env.example`（**只含占位符**）；`.env` 必须在 `.gitignore` 里且从未被 `git add`。
- 测试 mock 用伪造的 token / 项目 id / Cookie，绝不复用真实凭据。
- 若用户问"把 `.env` 贴给我看看"或类似请求，**拒绝**并说明替代方式（让用户自查、本地命令如 `grep -v '^#' .env | sed 's/=.*$/=<redacted>/'`）。

## 2. 简单优先

只写解决当前问题所需的最少代码，不做猜测式扩展。

- 不添加用户没有要求的功能。
- 不为只用一次的代码设计抽象层。
- 不加入没有被要求的灵活性、配置项或扩展点。
- 不为不可能出现的场景堆错误处理。
- 如果 200 行能改成 50 行，就回头简化。

自检问题：资深工程师看到这段实现，会不会觉得过度设计？如果会，就删减。

## 3. 外科手术式修改

只碰必须修改的地方。只清理自己造成的问题。

编辑已有代码时：

- 不顺手"优化"旁边的代码、注释或格式。
- 不重构没有坏的部分。
- 匹配项目现有风格，即使你个人会用另一种写法。
- 发现无关的废代码可以提一句，不要直接删除。

如果你的改动制造了无用内容：

- 删除由本次改动造成的无用 import、变量、函数。
- 不删除本来就存在的死代码，除非任务明确要求。

检查标准：每一行改动都应该能追溯到用户这次请求。

## 4. 目标驱动执行

把任务转成可验证的目标，然后循环到验证完成。

示例：

- "加校验" -> "先写非法输入测试，再让测试通过"
- "修 bug" -> "先写复现 bug 的测试，再修到测试通过"
- "重构 X" -> "重构前后都确认测试通过"

多步骤任务先写简短计划：

```text
1. [步骤] -> 验证：[检查方式]
2. [步骤] -> 验证：[检查方式]
3. [步骤] -> 验证：[检查方式]
```

## 5. ODS DML 抽取 — 行尾注释里的分号

`dataworks_agent.services.ods_holo.extract_dml_for_table` 用于从 DML 文件中
按段头 `-- 表名: cda.X` 抽取指定表的 DML 主体。早期实现用非贪婪正则
`insert into cda.X ... ?;` 匹配，遇到字段列表行尾注释里的分号
（例如 `-- 申请类型，1：取消申请 ;`）会提前截断，导致 DML 缺 from/where/;，
节点脚本无法执行。

修后实现按"段头边界 + 行尾注释剥离 + rfind 末尾 `;`"抽取。**不要回退到单段
非贪婪正则。**

校验：`uv run python -m dataworks_agent.scripts.verify_ods_params` 对 25 张
ODS 节点做线上 VFS 字节级 diff + 语义校验（必含 from/where/;，长度 ≥ 100），
CI 接入可作为发布前必过项。

## 6. 重构背景：cookie 鉴权 → 阿里云 OpenAPI (AK/SK)

### 动机
项目原来通过 `<DATAWORKS_BFF_ENDPOINT>` 走 DataWorks BFF + 浏览器
Cookie 鉴权。引入阿里云 DataWorks OpenAPI + AK/SK 鉴权，把能用 AK/SK 覆盖
的执行类操作切过去（建表/建节点/调度/DI/发布等）。

### ⚠️架构澄清（2026-07，修正早期"cookie 整体淘汰"的错误前提）
当前 AK/SK **只有开发环境权限**：可操作 dev schema/dev 数据源，能建表建节点
（真机验证通过），但**元数据浏览类 API 未授权**（`ListDataSources`/
`ListCatalogs`/`ListLineages` 等 403，这是架构预期、不是待批的临时缺口）。
**Cookie 链路不删除**，作为 AK/SK 权限缺口的**长期兜底**，两条链路按能力矩阵
分工并存：
- **AK/SK 处理**：dev 环境建表/建节点/调度/发布、DI（节点+DIJob）、Holo
  建节点、节点级血缘依赖、`get_table`/`list_tables` 元数据读。
- **Cookie 长期兜底**：数据源列表/数据源下表列举、元数据自由搜表、
  DataStudio 目录树、下游血缘 DAG、IDE 手动试跑 DI 节点。

### 已对齐方向
- AK/SK **只**通过环境变量 / `.env` 提供（`ALIYUN_ACCESS_KEY_ID` /
  `ALIYUN_ACCESS_KEY_SECRET`），不取 ECS RAM Role、不读 `~/.alibabacloud/credentials`。
- `cookie/`、`cdp_client.py`、`bff_client.py` **保留**（长期兜底通道，不删）；
  仅清理其中的**死代码**（如已确认无效的 Cookie 注入路径），不改变能力范围。
- 目标 OpenAPI 版本：**2024-05-18**（新版数据开发）；旧版工作空间（仅
  2020-05-18）走兼容路径，**不混用**。
- 优先用官方 SDK，避免手写签名（SDK 自动处理版本路由 + 重试）。

### B1–B3 安全修复（v9–v10，2026-07）

Import / 节点 / 表名三条链路统一加固，评审见 `reports/REVIEW.md` v9–v10：

| 代号 | 问题 | 修复入口 |
|---|---|---|
| **B1** | `/api/import` 路径遍历 | `routers/import_sql._resolve_import_root` — 仅允许 `import_allowed_roots` 或 `sql_template_root` 下路径 |
| **B2** | 破坏性操作绕过 guard | `api_clients/destructive_guard.guard_node_op` — MCP `execute_ddl`、BFF `delete_package`、OpenAPI offline |
| **B3** | 表名/SQL 拼接注入 | `schemas.assert_safe_table_name` — **唯一**标识符校验入口；ods_di `target_table` 等同源校验 |

相关 v10 项：`middleware/client_ip.py`（Cookie 本机端点用 TCP peer 防 XFF 伪造）、
`require_write_access` 覆盖 import 写端点、`COOKIE_ENCRYPTION_KEY` 启动强制 ≥16 字符。

**v11 反代部署**：配置 `TRUSTED_PROXIES`（如 `<TRUSTED_PROXY_IP>`）后挂载
`middleware/proxy_headers.ProxyHeadersMiddleware`，`IPIsolationMiddleware` 使用
解析后的 `request.client.host`；未配置时不信 X-Forwarded-For。绑定非 loopback 且
`TRUSTED_PROXIES` 为空时启动 WARNING。

### SDK 接入骨架（**待 region / endpoint 落定后填具体值**；包名/类名按
官方 SDK 文档校正后再用）

> 阿里云官方 Python SDK 各语言包发布在 PyPI / Maven / npm，搜索
> `alibabacloud_dataworks_public` 系列即可。**具体子包名（年份后缀
> 是 `20200518` 还是 `20240518`、是否带连字符）以 PyPI 实际包名为准**，
> 下面的代码骨架只是**结构示意**，不是可直接复制粘贴的最终代码。

```bash
# pip 包名以 PyPI 实际搜索结果为准
pip install alibabacloud_dataworks_public20240518 alibabacloud_tea_openapi
```

```python
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_dataworks_public20240518.client import Client

credentials = open_api_models.Credential(
    access_key_id=os.environ["ALIYUN_ACCESS_KEY_ID"],
    access_key_secret=os.environ["ALIYUN_ACCESS_KEY_SECRET"],
)
config = open_api_models.Config(
    credential=credentials,
    region_id=os.environ["DATAWORKS_REGION"],   # 按工作空间实际 region
    endpoint=os.environ["DATAWORKS_OPENAPI_ENDPOINT"],
)
client = Client(config)
```

### `bff_client` 22 方法 → OpenAPI 映射（顶层）

| 域 | bff_client 方法 | OpenAPI 2024-05-18 |
|---|---|---|
| 节点 | `create_node` / `update_node` | `CreateNode` / `UpdateNode` / `UpdateNodeScript` |
| 节点 | `get_node_list` | `ListNodes` |
| 节点 | `get_file` / `get_node_code` | `GetNodeScript` |
| 调度 | `update_vertex` | `UpdateNodeSchedule` |
| 调度 | `get_vertex` | `GetNodeSchedule` |
| 发布 | `deploy_nodes` | `DeployNode` / `BatchDeployNodes` |
| 工作流 | `get_node_parents_by_depth` | `ListNodeDependencies` / `UpdateWorkflowDependencies` |
| 元数据 | `search_tables` | `SearchMetaTables` |
| 元数据 | `get_creation_ddl` | `GetMetaTableDetailInfo` |
| 血缘 | `list_lineage` / `get_upstream_tasks` | `GetMetaColumnLineage` |
| 数据源 | `list_datasources` / `list_datasource_tables` | `ListDataSources` + DataIntegration 域 |
| 集成 | `create_di_node` / `create_di_executor_job` / `write_executor_config` | `CreateSyncTask` / `UpdateSyncTask` |
| SQL | `execute_sql` / `wait_job` / `get_query_result` | **DataWorks OpenAPI 公开版本没有等价方法**（用户贴的清单里未列出 SQL 提交 / 轮询）。替代方案待定：① 走 ODPS SDK（`alibabacloud_odps_sdk`）做 MaxCompute 提交；② 改成"通过调度系统跑"——把"手动 run"的能力从项目里拿掉。**本项目大多数 SQL 提交本就由 DataWorks 调度系统自己跑**，手动跑分支用例很少。 |

> ⚠️ 上表里 `bff_client` → OpenAPI 的方法名映射基于你贴的能力清单反推
> （用户贴的 2024-05-18 能力总览）。具体方法名在 [OpenAPI 调试器]
> (https://next.api.aliyun.com/product/dataworks-public) 里以真实命名为准；
> 上表作为接口域级映射（节点/调度/血缘/集成/元数据），方法名在写
> `openapi_client.py` 时按官方命名再确认。

### 关键注意事项
- **版本兼容**：2024-05-18 与 2020-05-18 不能混用，混调会 `InvalidParameter`。
  旧版工作空间（未开启"新版数据开发"）走 2020-05-18 子包。
- **RAM 授权现状**（⚠️2026-07 澄清，不再是"先给 FullAccess 后收敛"的计划）：当前 AK/SK
  账号为开发环境权限，未获 `AliyunDataWorksFullAccess` 或元数据类细粒度策略；不假设会
  升级到该权限，403 的调用点固定走 Cookie 兜底（见 §6 顶部"架构澄清"与 §7.5）。
- **流控**：官方未公开 QPS 上限，>50 QPS 做指数退避；批量操作走 `Batch*` 类 API。
- **地域 endpoint**：上海 `dataworks.cn-shanghai.aliyuncs.com`；深圳
  `<DATAWORKS_OPENAPI_ENDPOINT>`；按工作空间 region 选。
- **执行 SQL 边界**：`execute_sql` / `wait_job` / `get_query_result` 不在
  DataWorks OpenAPI 公开版本里。替代方案待定（见上方 SQL 行说明）。

### 状态
- 2026-07-02 起：`bff_client` 22 方法的能力分工已澄清（见上方映射表）。
- **2026-07 架构澄清**：`bff_client`/`cookie/`/`cdp_client.py` **不删除**，长期作为
  AK/SK 开发权限缺口的兜底（见本节顶部"架构澄清"）。本节作为协作背景与决策锚点。


## 7. DataWorks OpenAPI 2024-05-18 真机核实（Task 8 联调，2026-07 起）

以下为用真实 AK/SK 连 `<DATAWORKS_OPENAPI_ENDPOINT>`（项目 ID 由本地 `.env` 提供）跑
`scripts/probe_openapi.py` 只读探针核实的结论，**以此为准，勿再按 design 假设猜**。

### 7.1 依赖版本坑（必须）
`alibabacloud_tea_openapi 0.3.14` 要求 `CredentialModel.provider_name`，而
`alibabacloud_credentials 0.3.6` 没有该属性 → 首次调用报
`AttributeError: 'CredentialModel' object has no attribute 'provider_name'`。
**修复**：`alibabacloud-credentials>=1.0.0`（已锁 1.0.9）。回退会再次触发。

### 7.2 方法名/参数（真实 SDK）
- `list_nodes(page_size=...)`：**PageSize=5 报 InvalidPageSize**，用 ≥10。返回
  `body.PagingInfo.Nodes[]`。ListNodesRequest 无 name 过滤字段（按名搜节点得客户端过滤或另寻接口）。
- `list_tables`：**ParentMetaEntityId 强制**，不是自由文本搜表；元数据搜表需先有父实体 id。
- `list_lineages`：**需 RAM 权限 `dataworks:ListLineages`**，否则 403030。当前账号
  未授权。→ 表/字段级血缘暂不可用；**节点级依赖用 `list_node_dependencies` 替代**。

### 7.3 节点 Spec = FlowSpec JSON（8b 建/改节点的关键）
`get_node(id)` 返回 `body.Node`，含 `Node.Spec`（字符串，需 json.loads）：
```
{"version":"1.1.0","kind":"CycleWorkflow","spec":{"nodes":[{
  "id","recurrence":"Normal","timeout":0,"instanceMode":"Immediately",
  "rerunMode":"Allowed","rerunTimes","rerunInterval","autoParse":false,
  "datasource":{"name":"dataworks","type":"odps"},
  "script":{"id","path":"业务流程/.../02_DWS/<name>","language":"odps-sql",
            "runtime":{"command":"ODPS_SQL","commandTypeId":10,"cu":"0.25"},
            "content":"<SQL 正文>"},
  "trigger":{...},"strategy":{...}
}]}}
```
→ `create_node(spec=...)`/`update_node(id, spec=...)` 的 spec 即构建此 FlowSpec；
节点脚本正文在 `spec.nodes[0].script.content`（替代 BFF 的 update_node 写正文）。

### 7.4 list_node_dependencies 响应（8c 血缘 BFS 的关键）
`list_node_dependencies(node_id)` 返回 `body.PagingInfo.Nodes[]`，每个父节点结构同
list_nodes 的 Node：`Id`(节点id)、`Name`(≈产出表名)、`Script.Path`、
`Outputs.NodeOutputs[{Data:"dataworks.<table>"}]`、`Trigger.Cron`、`TaskId`。
→ 映射 `bff.get_node_parents_by_depth`：父节点 id=`Node.Id`，父表名=`Node.Name`。
→ 映射 `bff.get_node_code`：`get_node(id).Node.Spec` 解析取 `script.content`。

### 7.5 AK/SK 权限边界（开发权限，非临时待批）
当前 AK/SK 账号为**开发环境权限**，以下 403 是架构预期、非"申请一下就能通"：
- 表/列血缘（`ListLineages`/`GetMetaColumnLineage` 类）：403，需 `AliyunDataWorksFullAccess`
  或细粒度 `dataworks:ListLineages`（生产级权限，不在开发权限范围）。**下游血缘固定走 Cookie**
  （`routers/lineage.py` 的 `DataWorksClient.list_lineage`）。
- `ListDataSources`/`ListCatalogs` 等元数据浏览域：403，同理**固定走 Cookie**。
- 按表名反查产出节点（resolve_root_node 场景）：`list_nodes` 无 name 过滤，分页匹配
  `Outputs.NodeOutputs[].Data == dataworks.<table>` 性能一般；DataMap 血缘反查因上述权限限制不可用。
- 若后续拿到生产级 RAM 权限，可重新评估把这批切到 AK/SK；在此之前视为长期分工，不要
  当作"迁移未完成"处理。

### 7.6 CreateNode 建节点到指定业务流程文件夹（真机核实 2026-07，纯 AK/SK）
把节点建进 `业务流程/106_广告报告/MaxCompute/数据开发/00_ODS` 这类目录，**不需要**
先有业务流程容器（此前误判"必须挂 workflow-definition"是错的）：
- **关键**：`create_node(spec=<FlowSpec>, container_id=None, scene="DATAWORKS_PROJECT")`。
  - `container_id` 传文件夹 uuid 会报 `内部节点的容器对象: 未找到 <uuid>`（400）——
    文件夹 uuid 不是合法容器；**正确做法是不传 container_id**。
  - `scene` 必填，缺失报 `MissingScene`。新版数据开发用 `DATAWORKS_PROJECT`。
  - 节点落位完全由 FlowSpec 里 `spec.nodes[0].script.path` 决定（末尾带节点名）。
    真机验证节点精准落在 `.../00_ODS/<name>`。
- **FlowSpec enum 坑**：
  - `inputs.nodeOutputs[].sourceType` 只认 `Manual` / `System`，**传 `Normal` 报
    `Enum not found. Enum: SourceType Value:Normal`**。显式上游依赖用 `Manual`。
  - `spec.flow[].depends[].type` 才用 `Normal`（表级血缘依赖）/ `CrossCycleDependsOnSelf`（自依赖）。
  - `flowspec.build_node_flowspec(upstream_refs=[...])` 已按此实现：inputs 用 Manual、
    flow.depends 用 `{type:Normal, sourceType:Manual}`。DWD→ODS 硬依赖真机验证通过。
- **删节点**：`delete_node(id, project_id)` 可用（真机验证 Success:true）；高频操作会
  `Throttling.User`（9990020002），需退避重试。
- **发布**：以上仅建/改草稿（deployStatus=Saved）。发布另走 Deployment 域 + Publish_Gate 人工授权。

### 7.7 DI（数据开发数据集成节点）FlowSpec 结构（真机核实 2026-07）
DataWorks 有两种"DI"：① **数据集成作业 DIJob**（`CreateDIJob` 系，整库/实时同步，独立模块）；
② **数据开发里的 DI 节点**（挂调度、DataX 向导，项目 `ods_di` 用的就是这种）。二者都有 AK/SK。
- **DI 节点 = SQL 节点同一 FlowSpec 外壳**，仅差：`script.language="json"`、
  `script.runtime={command:"DI",commandTypeId:23,cu:...}`、`spec.nodes[0].datasource=null`（DI
  无顶层数据源，reader/writer 各自在 content 里带）、`script.content` = DataX filespec JSON
  （`{type:"job",version:"2.0",steps:[reader/processor/writer],...}`，即 `build_di_task_config` 产出）。
  → `flowspec.build_node_flowspec(language="di", script_content=<DataX json>)` 即可建。
- **手动跑未发布 DI 节点**（bff 的 `create_di_executor_job`+`write_executor_config`）属 IDE 试跑，
  OpenAPI 无通用等价；DIJob 作业的手动重跑用 `start_dijob(force_to_rerun=True)`。

### 7.8 Holo 节点 FlowSpec + Holo SQL 执行边界（真机核实 2026-07）
- **建 Holo 节点 AK/SK 可行**（真机验证：建→回读→删除全通）：`script.language="holo"`、
  `runtime={command:"HOLOGRES_SQL",commandTypeId:1093,cu:...}`、`datasource={name:"dataworks_holo",type:"holo"}`
  （数据源名与 MaxCompute 的 "dataworks" 不同，配 `settings.holo_node_datasource`）。
  `build_node_flowspec(language="holo")` 已按此修正（commandTypeId 1093）。
  **路径约束**：Holo 节点须落在真实存在的 Hologres 目录树下（如 `业务流程/<域>/Hologres/数据开发/00_ODS/`），
  放到不存在的目录层级会 400「目录层级校验未通过」。
- **Holo SQL 执行方案（已定，不引入直连客户端）**：`IMPORT FOREIGN SCHEMA` 等 Holo 库内 SQL
  **随 DML 留在 Holo 节点内容里，由 DataWorks(HOLOGRES_SQL) 执行**，平台不直连 Holo。
  `IMPORT ... OPTIONS(if_table_exist 'update')` 幂等，每次运行安全。
  （原 bff 流程"平台先执行 IMPORT + comment_out_import"已移除。）
  → 无需 Hologres pg 连接客户端。`ensure_holo_table` 里执行的是 **MaxCompute DDL**（建 MC 源表，
  非 Holo SQL），有 AK/SK 等价（`MaxComputeClient.execute_ddl`，属 8a 接线）。

### 7.9 R18 — cache epoch 防 stale-write（v9–v10）

Dashboard / 列表缓存 miss 后跑慢 SQL 期间若被 `delete`  invalidate，旧结果不应写回：

```python
min_epoch = cache.peek_invalidation_epoch("dashboard")
result = await expensive_aggregate()
cache.set("dashboard", result, ttl=60, min_epoch=min_epoch)  # epoch 已推进则丢弃
```

- 实现：`cache/manager.py` — `_epochs`、`delete` 递增、`set(min_epoch=)`、`get_or_set` 同款模式。
- 订阅失效：`monitor._broadcast_task_status` 在 `TASK_STATUS_CHANGED` 时 `delete("dashboard")` +
  `invalidate_by_source("tasks")`。
- 可观测：`get_stats()["stale_writes"]` 计数；丢弃时 `logger.debug`。

### 7.10 R17 — engine publish → dashboard 实时刷新（v9–v10）

建模状态机 / engine 内部 transition 必须 publish，驱动 WS 与缓存失效：

- **发布点**：`modeling/engine._publish_task_status`（8 处）+ `routers/modeling._publish_task_status_changed`。
- **事件**：`EventBus.publish_async(TASK_STATUS_CHANGED, data={task_id, status, timestamp, request_id})`。
- **消费**：`routers/monitor._broadcast_task_status` — 失效 cache → fanout 所有 `/ws/tasks` 连接。
- **失败策略**：publish 失败 `logger.warning`（不拖死主链路）；WS 死连接 send 失败自动踢出。

## 8. 修改小功能后必须测试、重启与同步文档

完成任何小功能修改后：
- 运行受影响模块的 pytest 测试（uv run python -m pytest tests/integration/ -q --tb=short）
- **改完代码必须重启正在跑的服务再验证**（本项目 8085 上的 `python -m dataworks_agent.main` **不热加载**）：
  1. 查端口与进程启动时间（如 `netstat -ano | findstr 8085`）
  2. 停掉旧进程后重新启动（或明确请用户重启）
  3. 用 `/agent/capabilities`、实际聊天/API 请求确认新字段或新路径已加载
  4. **禁止**只说“代码已改完可用”，除非确认进程已重启且行为对上
  5. 前端 `vite` 开发服一般会热更新；**后端 Python / 已构建的 `frontend/dist` 静态资源改动都需要重启或重新 build**
- 如果开发过程中发现任何文档（spec、design、tasks）与实际实现不符，应立即更新文档以保持代码与文档一致
- 文档更新后，确认 CI 回归门无异常（uv run ruff check . + 全量 pytest）

## 9. Agent 开发规范

### 目录结构

```
dataworks_agent/agent/           # Agent 核心模块
├── core.py                      # 对话管理 + 上下文维护
├── nlu/                         # 自然语言理解
│   ├── intent_parser.py         # 意图识别
│   ├── entity_extractor.py      # 实体抽取
│   └── templates.py             # 意图模板（新增意图在此添加）
├── planner/                     # 任务规划
│   ├── task_planner.py          # 任务分解
│   └── task_graph.py            # 依赖排序
├── executor/                    # 工具执行
│   ├── tool_executor.py         # 工具调度（新增工具在此集成）
│   └── task_executor.py         # 任务执行器

frontend/src/components/agent/   # 前端对话组件
├── AgentChat.vue                # 主对话窗口
├── ChatMessage.vue              # 消息渲染
└── QuickActions.vue             # 快捷操作
```

### 开发流程

1. **新增意图**: 在 `nlu/templates.py` 添加意图模板，定义关键词匹配规则
2. **新增工具**: 在 `executor/tool_executor.py` 集成，注册到工具列表
3. **新增响应格式**: 在 `core.py` 添加格式化逻辑

### 测试要求

- 单元测试覆盖核心逻辑（意图识别、实体抽取、工具调度）
- 集成测试覆盖 API 端点（`/api/runtime/chat`、`/api/runtime/ws`）
- E2E 测试覆盖用户对话流程

## 10. 语义层与 Agent 平台架构

### 分层架构 (L0-L5)

```
L5: 持续自愈 + 语义自进化 + 可评测
    ├── SelfHealFlow (自愈流程)
    ├── Evaluator (可评测与反馈闭环)
    └── SemanticEvolver (语义自进化)

L4: Coordinator + 多 agent + 模型路由
    └── Coordinator (多专业 agent 协调器)

L3: MCP + 端到端 + 指标归因 + 数据质量 + 渠道
    ├── MCPServer (自建 AK/SK MCP Server)
    ├── Agent (端到端建模与对话查询)
    ├── MetricAttributor (指标归因诊断)
    ├── DQConsumer (数据质量消费)
    ├── DingTalkAdapter (钉钉群接入)
    └── FineReportAdapter (帆软报表接入)

L2: 语义知识图谱 + 无状态重放
    ├── SemanticGraph (语义知识图谱)
    ├── ReplayManager (无状态重放续跑)
    └── IsolationVerifier (隔离边界验证)

L1: 语义层 + 双向建模 + 解耦 + 审批
    ├── SemanticLayer (语义层服务)
    ├── ProposalGuard (确定性护栏)
    ├── RuntimeService (Agent Runtime)
    ├── PublishGate (审批闸口)
    ├── ForwardModelingFlow (正向建模)
    ├── ReverseModelingFlow (逆向建模)
    └── CaliberClarifier (口径澄清)

L0: 地基 (AK/SK + pyodps + LLM + Event Log)
    ├── Auth_Provider (AK/SK 鉴权)
    ├── OpenAPI_Client (DataWorks OpenAPI)
    ├── MaxCompute_Client (pyodps)
    ├── LLM_Service (LLM 服务)
    ├── EventLog (事件日志)
    └── DestructiveOpGuard (破坏性操作拦截)
```

### 核心模块位置

| 模块 | 位置 | 说明 |
|------|------|------|
| 语义层 | `semantic/layer.py` | 版本化语义定义、口径澄清 |
| 语义图谱 | `semantic/graph.py` | 融合血缘+语义+元数据 |
| Agent Runtime | `runtime/service.py` | 无状态执行、检查点、重放 |
| MCP Server | `mcp_server/server.py` | 六类工具、鉴权+审计 |
| 正向建模 | `runtime/forward_flow.py` | NL→DDL/DML/调度 |
| 逆向建模 | `runtime/reverse_flow.py` | 存量表→结构+语义 |
| 指标归因 | `runtime/attribution.py` | 口径澄清→根因分类 |
| 自愈流程 | `runtime/self_heal.py` | 调度失败/数据异常诊断 |
| 评测闭环 | `runtime/evaluator.py` | 质量指标+Badcase沉淀 |

## 12. OSS 外表抽取规范

OSS 数据源统一采用“外表 → ODS → DWD”链路，禁止直接 LOCATION 灌入 ODS：

- 外表位于 `<DEV_PROJECT>`，已存在则校验并复用，不存在才创建。
- ODS/DWD 位于 `<PROD_PROJECT>`；ODS 按 `ods_mc_ads_data__<source>_day/hour` 命名。
- ODS 先 `ADD IF NOT EXISTS PARTITION`，再 `INSERT OVERWRITE ... SELECT` 外表；DWD 从 ODS `INSERT OVERWRITE`，不由 OSS 流程预创建 DWD 分区。
- 生产代码和生成 SQL 不得出现 `LOAD OVERWRITE` 或 `FROM LOCATION`。
- 日 ODS 使用 `dt=${bizdate}`，小时 ODS 使用 `dt=${gmtdate}, ht=${hour_last1h}`；外表 `pt` 分区独立处理，缺失映射时返回上下文缺失，不猜值。

### 新增组件

| 组件 | 位置 | 说明 |
|------|------|------|
| 任务拆解器 | `agent/planner/task_decomposer.py` | 复杂任务自动拆解为可执行步骤 |
| 重试处理器 | `agent/executor/retry_handler.py` | 错误分类 + 指数退避重试 |
| 执行监控器 | `agent/monitor/execution_monitor.py` | 实时跟踪任务执行状态 |
| 任务执行面板 | `frontend/src/components/agent/TaskExecution.vue` | 可视化执行进度 |
| 执行进度显示 | `frontend/src/components/agent/ExecutionProgress.vue` | 步骤状态展示 |

### 扩展点

- `TaskPlanner._llm_plan()` — 集成 LLM 进行复杂任务规划
- `TaskExecutor._execute_with_retry()` — 错误恢复和重试机制
- `ExecutionMonitor` — 实时状态更新 API

### 测试要求

- 单元测试覆盖核心逻辑（任务拆解、重试策略、状态跟踪）
- 集成测试覆盖复杂任务拆解流程
- 前端组件测试覆盖执行面板渲染
