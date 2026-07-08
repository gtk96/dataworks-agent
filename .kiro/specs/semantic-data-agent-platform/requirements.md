# Requirements Document

## Introduction

本需求文档描述 dataworks-agent 的一次重大演进：把现有的"数仓建模自动化工具"升级为 **dataworks 的语义化数据基础设施层 + 领域特化 Agent 平台**（功能名 `semantic-data-agent-platform`）。

演进的北极星是：让本平台成为坐在 DataWorks / MaxCompute **之上**的一层，专注做两件外部产品不做的事——**统一语义层**（把散在人脑与配置里的指标定义、业务口径、维度关系、别名、权限收敛成机器可消费、版本化的单一事实源）与**统一 AI 接口**（自建 AK/SK 版 MCP server，带语义、权限、审计、上下文绑定，供外部 AI 与内部编排层调用）。平台明确**不重建**统一数据、统一元数据、统一计算这三层，因为 MaxCompute / DataWorks 已经提供。

本次演进遵循两条不可反的主线：

1. **鉴权与执行底座按能力矩阵分工**（⚠️2026-07 架构澄清，见 Requirement 1）：当前 AK/SK 仅有开发环境权限，因此不是"彻底抛弃 Cookie"，而是 AK/SK 处理其权限覆盖的执行类操作（DataWorks OpenAPI 2024-05-18 的节点/调度/发布/DI + MaxCompute pyodps 的建表/跑 SQL/取结果），Cookie 长期兜底 AK/SK 无权限的元数据浏览类操作（数据源/搜表/目录树/下游血缘）。两条链路长期并存分工，不追求淘汰 Cookie。
2. **演进顺序不可反**：先把底座（语义层）统一，再上 AI，禁止在旧平台上直接叠加聊天入口。

平台通过 **OpenAI 兼容网关**接入外部大语言模型（当前经 **OpenCode Zen** 网关接入，base_url `https://opencode.ai/zen/v1`，`model` / `api_key` 可配置、provider 无关，便于日后换私有化或通义而不改代码；`api_key` 仅置于 `.env`，绝不入库入 git）。遵守核心安全原则：**LLM 只做提议、规划、推理；确定性工具做校验；人做审批**。生成的一切 DDL 必须通过词根校验与命名/SQL 规范校验；建表与发布前必须经过人工确认（沿用现有 dry_run / preview 模式）。**数据边界**：只把 schema 与元数据发给 LLM，绝不发送生产数据行；已知并接受 schema/元数据会离开阿里云进入外部模型（OpenCode Zen 不在阿里云内）这一残余风险（如需消除，可切换为私有化/内网 LLM，业务代码不变）。

建模能力同时支持两个方向：**正向建模**（从业务需求/自然语言从头产出新模型）与**逆向建模**（从 DataWorks / MaxCompute 已存在的表、SQL、调度节点反向抽取结构、血缘与语义候选）。逆向建模是语义层与语义知识图谱的主要 bootstrap 手段——存量资产的语义不靠全部从头重建，而靠对既有资产的逆向抽取纳管。

需求按"自动驾驶 L0-L5"类比分层组织，逐层解锁 agent 自主度，从"AK/SK 地基"到"值班级自主"。此外，现有资产（`modeling/`、`governance/`、`standards/`、`naming/`、`task_engine/state_machine`、`FastAPI + Vue + SQLite` 主体）予以保留复用，Cookie 链路（`cookie/`、`bff_client.py` 等）作为 AK/SK 权限缺口的长期兜底同样保留（见 Requirement 1）。整体设计遵循项目 CLAUDE.md 的"简单优先 / 外科手术式修改"原则，避免过度设计为通用 agent 平台。

**主语言与技术栈**：后端主语言为 **Python 3.12**（pyodps 与 DataWorks SDK 原生支持最佳、LLM/sqlglot 生态最全），前端为 **Vue + TypeScript**，沿用现有技术栈不更换。

**部署与多人使用**：平台部署为 dataworks 阿里云 VPC 内的**单一共享服务**（单进程单节点），紧邻 DataWorks/MaxCompute，以**服务级 AK/SK** 统一对接阿里云。状态存储沿用 **SQLite（WAL 模式）**，满足团队级低并发；未来若扩展为多副本或高并发写再评估迁移服务端 DB。多用户以 **IP 区分**作归属与隔离（复用现有 IP 隔离中间件），审计按 IP 记录。须知 **IP 区分是软隔离而非身份认证**，因此平台必须在网络层收口（绑定内网 + 安全组白名单，不暴露公网），对生产写操作照样走人工审批闸口，将来可叠加共享口令或接入 SSO 而不重构。

## Glossary

- **The_Platform**：本系统整体，即演进后的 dataworks-agent（semantic-data-agent-platform），坐在 DataWorks / MaxCompute 之上的语义化数据基础设施 + 领域特化 Agent 平台。
- **Auth_Provider**：AK/SK 鉴权组件。仅从环境变量 `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET` 读取凭证，不使用 ECS RAM Role，不读取本地 credentials 文件。
- **OpenAPI_Client**：`openapi_client.py`，封装 DataWorks OpenAPI 2024-05-18（`alibabacloud-dataworks-public20240518` + `alibabacloud-tea-openapi`），负责节点 CRUD、调度、发布、元数据、血缘、数据源、DI 同步任务。
- **MaxCompute_Client**：`maxcompute_client.py`，封装 MaxCompute pyodps SDK，负责建表、执行 SQL、查询结果。
- **BFF_Client**：现有 `bff_client.py`，基于 Cookie 的 DataWorks BFF 客户端。⚠️不被淘汰——因 AK/SK 仅具开发环境权限，元数据浏览类（数据源/搜表/目录树/下游血缘）等能力长期依赖 BFF_Client 兜底，与 OpenAPI_Client / MaxCompute_Client 长期并存。
- **LLM_Service**：外部大语言模型服务，通过 OpenAI 兼容网关访问（当前为 OpenCode Zen，base_url `https://opencode.ai/zen/v1`），`model` / `api_key` 可配置、provider 无关；数据边界为仅可发送 schema / 元数据。
- **LLM_Router**：模型分级路由组件，按任务复杂度路由到配置的模型档位（轻量 / 常规 / 复杂）；若仅配置单一模型，则全部路由到该模型。
- **Semantic_Layer**：统一语义层，机器可消费、版本化的指标定义、业务口径、维度关系、别名、权限的单一事实源。
- **Semantic_Graph**：语义知识图谱，融合血缘、业务含义、元数据，作为 agent 的世界模型。
- **MCP_Server**：自建 AK/SK 版 MCP server，替代被删除的基于 Cookie 的外部 MCP，带语义、权限、审计、上下文绑定。
- **Agent_Runtime**：领域特化 agent 运行时，采用大脑（LLM 规划）与双手（工具执行）解耦、无状态设计。
- **Forward_Modeling**：正向建模 / 从头建模，从业务需求或自然语言出发，产出全新模型（DDL / DML / 调度配置），走"提议-验证-审批"闭环。
- **Reverse_Modeling**：逆向建模，从 DataWorks / MaxCompute 中已存在的表、SQL 脚本、调度节点出发，反向抽取表结构、反推字段映射与血缘、反推分层/业务域/更新方式，并由 LLM 产出业务含义/口径/别名候选，纳入 Semantic_Layer / Semantic_Graph 管理。
- **Event_Log**：可查询、可恢复、可审计的执行事实源，由现有 `intent_logger` + `task_step_logs` + `pipeline_step_logs` 升级而来。
- **Coordinator**：多专业 agent 的协调器，负责编排需求理解 / 架构 / 建模 / 治理 / 诊断 / 查询等专业 agent。
- **Deterministic_Tool**：确定性工具的统称，包括 `ddl_generator`、`root_checker`、分层校验、`ddl_checker`、`lineage_service` 等，输出可复现、不依赖 LLM。
- **Root_Checker**：词根校验器，校验字段名是否符合词根规范，数据源为本地 `standards/word_roots/词根.text` 字典或通过 pyodps 查询线上词根表。
- **DDL_Checker**：DDL 与命名 / SQL 规范校验器（`governance/ddl_checker.py`）。
- **Lineage_Service**：血缘服务（`governance/lineage_service.py`、`sql_lineage.py`），解析并存储表间血缘关系，并支持对存量调度节点代码的 BFS 抽取。
- **Table_Name_Parser**：表名解析器（`governance/table_name_parser.py`），从表名反推分层与结构信息。
- **Update_Mode_Inferer**：更新方式推断器（`governance/update_mode_inferer.py`），从表名反推更新方式。
- **Publish_Gate**：人工审批闸口，沿用现有 dry_run / preview 模式，在建表与发布前要求人工确认。
- **Dev_Schema**：开发环境 schema `dataworks_dev`，作为 agent 操作的兜底隔离边界。
- **Prod_Schema**：生产环境 schema `dataworks`。
- **Cost_Monitor**：成本可观测组件，统计 LLM 的 Token 用量、成本与耗时。
- **Persistent_Queue**：现有 `PersistentPipelineQueue`，带租约与 worker 机制的持久化任务队列。
- **Session**：一次建模或对话任务的会话上下文，由 `modeling_tasks` / `pipeline_tasks` 承载，以 `session_id` 标识。
- **LLM_API_Key**：访问 LLM_Service 所需的 API Key，通过环境变量 / `.env` 提供。
- **Shared_Service**：部署形态——运行在 dataworks 阿里云 VPC 内的单一共享服务（单进程单节点），以服务级 AK/SK 统一对接阿里云。
- **IP_Identity**：以来源 IP 作为多用户任务归属与隔离依据（复用现有 IP 隔离中间件），用于归属与审计；属软隔离，非身份认证。
- **Standards_Bundle**：既有数仓规范内容集合，含 `warehouse/*.yaml`（分层引用规则、主题域、更新方式、类型映射、字段后缀规则）、`standards/steering/*.md`（数仓建设 / 字段命名 / Hologres 命名 / SQL 开发规范）与 `standards/word_roots/词根.text`，作为 Semantic_Layer 与确定性护栏的初始机器可读内容。
- **DataWorks_DQC**：DataWorks 数据质量（Data Quality）能力，提供质量规则定义、监控与告警；平台消费其规则与结果，不重建其执行引擎。
- **Quality_Signal**：质量 / 信任信号（新鲜度、完整性、唯一性、质量状态等），附着于表或指标，供 agent 判断数据可信度。
- **Runtime_Protocol_Object**：Agent_Runtime 对外暴露的稳定协议对象集合——Session、Run、Step、Event、Artifact、Checkpoint，与生命周期操作 stream / interrupt / resume / cancel / retry 一起构成不随框架更迭而变的契约。
- **Run**：一次具体执行边界，回答"这次跑了什么"，承载超时、取消、成本、审批与最终结果；隶属于某个 Session。
- **Step**：Run 内部一个可观测执行单元（一次 LLM 调用 / 工具调用 / 校验 / 子任务），由 `task_step_logs` / `pipeline_step_logs` 承载。
- **Checkpoint**：可恢复的执行快照，用于中断恢复、错误回滚与重放。
- **Artifact**：agent 产出的正式结果（DDL / DML / 报告等），可引用并可追溯到产生它的 Run，由 `artifacts` 表承载。
- **Badcase**：被确定性校验或人工审批拒绝的 agent 产出案例，结构化记录用于评测与改进。
- **Metric_Attribution**：指标归因诊断——针对业务反馈的指标异常，按"口径澄清 → 血缘逐层数值下钻 → 根因分类 → 证据结论"的流程定位原因。
- **Anomaly_Report**：业务反馈的指标异常请求（含指标、时间、维度、预期），由 The_Platform 解析为一次 Session / Run。
- **DingTalk_Adapter**：钉钉群机器人接入适配器，接收 @机器人 的异常反馈消息、回帖诊断结论，并复用钉钉发送者身份作归属。
- **User_Directory**：现有钉钉用户表与内部用户表的组合，用于将钉钉用户解析为内部用户及其团队 / 组织编码。
- **Permission_Model**：按团队（Team）与组织编码（Org_Code）进行的授权模型，决定请求方可访问的数据范围与可执行操作。
- **Web_UI**：面向数据工程师的 Vue 前端，提供建模、预览、审批、血缘、治理与产物管理，支持钉钉扫码登录获取身份。
- **FineReport_Adapter**：帆软报表接入适配器，让业务用户从报表上下文发起指标异常诊断；报表口径以 Semantic_Layer 为准。

---

## Requirements

## L0 —— 地基：AK/SK 重构 + pyodps + LLM 接入 + Event Log 升级为事实源

### Requirement 1: AK/SK 与 Cookie 按能力矩阵长期分工（⚠️2026-07 架构澄清，替代原"淘汰 Cookie 鉴权链路"）

**User Story:** 作为平台维护者，我想让 AK/SK 处理其权限范围内的执行类操作、Cookie 长期兜底 AK/SK 权限缺口，以便在当前 AK/SK 仅有开发环境权限的约束下，平台仍能覆盖生产环境的必要能力，而不是错误地假设 Cookie 可以被完全淘汰。

**背景**：当前 AK/SK 账号为**开发环境权限**——可操作 Dev_Schema / dev 数据源，且真机验证过可在生产空间（项目 ID 由本地 `.env` 配置）完成建表、建节点；但**元数据浏览类 API（数据源列表、数据源下表列举、元数据自由搜表、DataStudio 目录树、下游血缘 DAG）未获授权，返回 403**。这是权限架构的既定边界，不是临时待批的缺口。因此 Cookie 链路（`cookie/`、`api_clients/cdp_client.py`、`api_clients/bff_client.py`、`mcp/pool.py`）**不删除**，作为上述能力的长期兜底通道。

#### Acceptance Criteria

1. THE The_Platform SHALL 保留 `cookie/` 目录、`api_clients/cdp_client.py`、`api_clients/bff_client.py`、`mcp/pool.py` 四个基于 Cookie 的模块，不作删除。
2. THE The_Platform SHALL 对每个执行类调用点，优先尝试 OpenAPI_Client / MaxCompute_Client（AK/SK）；WHEN AK/SK 因权限不足（如 403）或客户端不可用而失败时, THE The_Platform SHALL 降级到对应的 Cookie 链路方法完成该调用。
3. THE The_Platform SHALL 将以下能力固定标注为"长期走 Cookie"，不纳入迁移到 AK/SK 的范围：数据源列表与数据源下表列举、元数据自由搜表、DataStudio 目录树浏览、下游血缘 DAG 查询、IDE 内手动试跑未发布的 DI 节点。
4. THE The_Platform SHALL 将以下能力标注为"AK/SK 已覆盖"：dev/prod 环境的建表、建节点（含 Holo、DI 节点）、调度配置、节点删除、DI 同步作业（DIJob）、节点级上游依赖查询、`get_table`/`list_tables` 元数据读取。
5. IF 代码中存在对 Cookie 模块的引用, THEN THE The_Platform SHALL 视为正常的兜底路径，不视为待清理的技术债；仅当引用路径本身已确认无效（如死代码）时才允许清理。
6. WHEN The_Platform 启动时, THE The_Platform SHALL 同时初始化 AK/SK 执行底座与 Cookie 兜底链路；缺失 Cookie 配置时 AK/SK 覆盖范围内的功能仍可正常工作，缺失 AK/SK 凭证时 Cookie 覆盖范围内的功能仍可正常工作。

### Requirement 2: AK/SK 统一鉴权

**User Story:** 作为平台维护者，我想让一切阿里云鉴权统一走 AK/SK，以便凭证来源单一、可控、可审计。

#### Acceptance Criteria

1. THE Auth_Provider SHALL 仅从环境变量 `ALIYUN_ACCESS_KEY_ID` 与 `ALIYUN_ACCESS_KEY_SECRET` 读取访问凭证。
2. THE Auth_Provider SHALL 不从 ECS RAM Role 获取凭证。
3. THE Auth_Provider SHALL 不读取本地 credentials 文件（例如 `~/.alibabacloud/credentials`）。
4. IF 环境变量 `ALIYUN_ACCESS_KEY_ID` 或 `ALIYUN_ACCESS_KEY_SECRET` 缺失, THEN THE Auth_Provider SHALL 在启动阶段返回明确的缺失凭证错误并阻止依赖阿里云的操作执行。
5. THE Auth_Provider SHALL 将访问凭证提供给 OpenAPI_Client 与 MaxCompute_Client 复用同一份 AK/SK。

### Requirement 3: DataWorks OpenAPI 执行底座（OpenAPI_Client）

**User Story:** 作为建模工程师，我想通过 DataWorks OpenAPI 2024-05-18 完成节点、调度、发布等 AK/SK 权限覆盖的操作，以便在开发环境权限范围内稳定执行，而不依赖当次会话的浏览器登录状态。

#### Acceptance Criteria

1. THE OpenAPI_Client SHALL 基于 `alibabacloud-dataworks-public20240518` 与 `alibabacloud-tea-openapi` SDK 实现。
2. THE OpenAPI_Client SHALL 提供节点 CRUD、调度配置、发布、DI 同步任务能力，以及元数据查询、血缘查询、数据源列表的方法实现；WHERE 当前 AK/SK 账号对某方法返回权限不足错误（如 403）, THE The_Platform SHALL 按 Requirement 1 的能力矩阵降级到 BFF_Client。
3. THE OpenAPI_Client SHALL 仅调用 DataWorks OpenAPI 2024-05-18 版本接口，不与 2020-05-18 版本接口混用。
4. WHEN OpenAPI_Client 调用任一 DataWorks OpenAPI 时, THE OpenAPI_Client SHALL 使用 Auth_Provider 提供的 AK/SK 完成签名鉴权。
5. WHEN DataWorks OpenAPI 返回可重试的流控错误时, THE OpenAPI_Client SHALL 以指数退避策略重试请求。
6. IF DataWorks OpenAPI 返回不可重试的错误, THEN THE OpenAPI_Client SHALL 返回包含错误码与错误信息的失败结果。

### Requirement 4: MaxCompute 执行底座（MaxCompute_Client）

**User Story:** 作为建模工程师，我想通过 MaxCompute pyodps SDK 完成建表、执行 SQL 与查询结果，以便替代原基于 Cookie 的 `execute_sql` / `wait_job` / `get_query_result` / `execute_ddl`。

#### Acceptance Criteria

1. THE MaxCompute_Client SHALL 基于 MaxCompute pyodps SDK 实现建表、执行 SQL 与查询结果能力。
2. WHEN MaxCompute_Client 建立连接时, THE MaxCompute_Client SHALL 使用 Auth_Provider 提供的 AK/SK 完成鉴权。
3. WHEN 建表或数据操作 SQL 被提交时, THE MaxCompute_Client SHALL 提交作业并轮询直至作业到达成功或失败的终态。
4. WHEN 查询作业成功完成时, THE MaxCompute_Client SHALL 返回结构化的查询结果集。
5. IF 提交的 SQL 作业执行失败, THEN THE MaxCompute_Client SHALL 返回包含失败原因的错误结果。

### Requirement 5: BFF 方法能力映射（⚠️替代原"BFF 方法迁移映射"——不追求全量迁移与删除）

**User Story:** 作为平台维护者，我想清楚知道 `bff_client.py` 的 22 个方法里哪些已有 AK/SK 等价、哪些因权限边界长期保留在 BFF_Client，以便调用方按能力矩阵正确选择执行路径，而不是假设所有方法终将迁移完毕。

#### Acceptance Criteria

1. THE The_Platform SHALL 将 `bff_client.py` 中节点 CRUD、调度配置、发布、DI 同步作业相关方法迁移到 OpenAPI_Client，作为 AK/SK 优先路径。
2. THE The_Platform SHALL 将 `bff_client.py` 中建表与 SQL 执行相关方法（`execute_sql`、`wait_job`、`get_query_result`、`execute_ddl` 及其等价能力）迁移到 MaxCompute_Client，作为 AK/SK 优先路径。
3. THE The_Platform SHALL 保留 `bff_client.py` 中数据源列表、数据源下表列举、元数据自由搜表、DataStudio 目录树浏览、下游血缘 DAG 查询、IDE 手动试跑 DI 节点相关方法，作为长期兜底路径，不纳入迁移范围。
4. THE The_Platform SHALL NOT 移除 `api_clients/bff_client.py`。
5. THE The_Platform SHALL 保证第 1、2 条迁移的方法在对应调用点具备"AK/SK 优先、失败或权限不足时降级 BFF_Client"的调用顺序。

### Requirement 6: 词根校验数据源本地化

**User Story:** 作为建模工程师，我想让词根校验不再依赖 Cookie 链路，以便字段命名校验在 AK/SK 底座上可用。

#### Acceptance Criteria

1. THE Root_Checker SHALL 从本地 `standards/word_roots/词根.text` 字典读取词根规范。
2. WHERE 配置为查询线上词根表, THE Root_Checker SHALL 通过 MaxCompute_Client（pyodps）查询线上词根表获取词根规范。
3. WHEN 待校验字段名的下划线拆分片段全部命中词根规范时, THE Root_Checker SHALL 返回校验通过结果。
4. IF 待校验字段名存在未命中词根规范的片段, THEN THE Root_Checker SHALL 返回包含非法片段与修正建议的校验失败结果。

### Requirement 7: 引入 LLM_Service 与分级路由（provider 无关）

**User Story:** 作为平台维护者，我想通过 OpenAI 兼容网关接入可配置的外部 LLM 并按任务复杂度分级路由，以便控制 Token 成本且日后可无缝更换 provider。

#### Acceptance Criteria

1. THE LLM_Service SHALL 通过 OpenAI 兼容接口访问外部大语言模型，其 `base_url`、`model`、`api_key` 均从配置 / 环境变量读取。
2. THE LLM_Service SHALL 保持薄封装，不引入 langchain 或 llamaindex 等重型框架，且不将 provider 细节硬编码。
3. WHEN 任务复杂度被判定后, THE LLM_Router SHALL 将请求路由到配置的对应模型档位（轻量 / 常规 / 复杂）。
4. WHERE 仅配置了单一模型, THE LLM_Router SHALL 将所有请求路由到该模型。
5. IF LLM_API_Key 缺失, THEN THE LLM_Service SHALL 返回明确的密钥缺失错误并阻止 LLM 调用。
6. WHERE 需要更换 LLM provider, THE The_Platform SHALL 仅通过修改配置（`base_url` / `model` / `api_key`）完成切换而不改动业务代码。

### Requirement 8: LLM 数据边界

**User Story:** 作为数据安全负责人，我想确保只有 schema 与元数据被喂给 LLM，以便生产数据行永不出境。

#### Acceptance Criteria

1. WHEN The_Platform 构造发送给 LLM_Service 的上下文时, THE The_Platform SHALL 仅包含 schema 与元数据。
2. THE The_Platform SHALL 不将生产数据表的数据行内容发送给 LLM_Service。
3. IF 待发送给 LLM_Service 的上下文中检测到生产数据行内容, THEN THE The_Platform SHALL 阻止该次发送并记录违规事件到 Event_Log。
4. THE The_Platform SHALL 允许通过将 LLM_Service 切换为私有化 / 内网部署来消除 schema/元数据外泄的残余风险，且该切换不改动业务代码。

### Requirement 9: Event Log 升级为唯一事实源

**User Story:** 作为平台维护者，我想把现有 `intent_logger` + `task_step_logs` + `pipeline_step_logs` 升级为可查询、可恢复、可审计的执行事实源，以便所有行为可追溯、可重放。

#### Acceptance Criteria

1. THE Event_Log SHALL 复用并升级 `intent_logger`、`task_step_logs`、`pipeline_step_logs` 作为执行事实源。
2. WHEN The_Platform 执行任一状态变更或工具调用时, THE Event_Log SHALL 以 `session_id` 关联记录该事件的意图、目标、结果与耗时。
3. THE Event_Log SHALL 支持按 `session_id` 查询该会话的完整事件序列。
4. WHEN 按 `session_id` 查询时, THE Event_Log SHALL 按事件发生顺序返回事件序列。

## L1 —— 语义层 v1 + 双向建模 + 大脑/双手解耦（只读建议）

### Requirement 10: 语义层单一事实源（Semantic_Layer v1）

**User Story:** 作为数据治理负责人，我想把词根、业务口径、维度关系、别名与权限收敛为机器可读的单一事实源，以便消除散落在人脑与配置中的口径分歧。

#### Acceptance Criteria

1. THE Semantic_Layer SHALL 以机器可消费格式存储词根、业务口径、维度关系、别名与权限定义。
2. THE Semantic_Layer SHALL 为每条语义定义维护版本号。
3. WHEN 一条语义定义被修改时, THE Semantic_Layer SHALL 递增该定义的版本号并保留历史版本。
4. WHEN 给定一个指标或字段标识时, THE Semantic_Layer SHALL 返回该标识对应的唯一当前口径定义。
5. IF 同一指标存在多个冲突的口径定义, THEN THE Semantic_Layer SHALL 拒绝写入并返回冲突详情。
6. THE Semantic_Layer SHALL 支持以 Reverse_Modeling 对存量资产逆向抽取的结果作为其初始 bootstrap 内容来源。
7. THE Semantic_Layer SHALL 以 Standards_Bundle（`warehouse/*.yaml` + `standards/steering/*.md` + 词根字典）作为其初始 bootstrap 内容来源之一，与 Reverse_Modeling 抽取结果并列，涵盖分层引用规则、主题域、更新方式后缀、字段类型规则与词根规范。
8. THE Semantic_Layer SHALL 为每张表 / 每个指标携带 Quality_Signal（新鲜度、完整性、唯一性、质量状态），供 agent 判断可信度。
9. THE Semantic_Layer SHALL 作为人、agent 与报表工具（如帆软）共享的唯一口径来源，以支持"同问同答"，并使报表口径可与其对齐。

### Requirement 11: 建模引擎双向能力（正向 + 逆向）

**User Story:** 作为建模工程师，我想让建模引擎同时支持从头（正向）建模与对存量资产的逆向建模，以便既能创建新模型，也能把已有数仓资产纳入语义治理。

#### Acceptance Criteria

1. THE The_Platform SHALL 同时提供 Forward_Modeling 与 Reverse_Modeling 两种建模模式。
2. WHEN 用户从业务需求或自然语言发起建模时, THE The_Platform SHALL 以 Forward_Modeling 模式产出全新模型（DDL / DML / 调度配置）。
3. WHEN 用户针对 DataWorks / MaxCompute 中已存在的表、SQL 或调度节点发起建模时, THE The_Platform SHALL 以 Reverse_Modeling 模式反向还原其结构、血缘与语义候选。
4. THE Forward_Modeling 与 Reverse_Modeling SHALL 共享同一套确定性校验（Root_Checker、DDL_Checker、分层依赖校验）与 Publish_Gate 审批闸口。

### Requirement 12: 逆向建模（Reverse_Modeling）

**User Story:** 作为数据治理负责人，我想从存量表 / SQL / 节点逆向抽取结构、血缘与语义候选并批量纳管，以便用存量资产 bootstrap 语义层与语义图谱，而不必全部从头建模。

#### Acceptance Criteria

1. WHEN 给定一张已存在的表时, THE Reverse_Modeling SHALL 通过 MaxCompute_Client 或 DataWorks 元数据抽取该表的结构（字段、类型、分区、注释）。
2. WHEN 给定一段已存在的节点 SQL 或脚本时, THE Reverse_Modeling SHALL 解析该 SQL 反推字段映射与表间血缘（复用 Lineage_Service 的 parse-sql-lineage 与 parse-ddl 能力）。
3. WHEN 给定一张已存在表的表名时, THE Reverse_Modeling SHALL 通过 Table_Name_Parser 与 Update_Mode_Inferer 反推其分层、业务域与更新方式。
4. WHEN 对存量表执行逆向建模时, THE Reverse_Modeling SHALL 由 LLM_Service 产出业务含义、口径与别名的候选提议。
5. THE Reverse_Modeling SHALL 支持对多张存量表批量执行逆向建模，作为 Semantic_Layer 与 Semantic_Graph 的初始 bootstrap 来源。
6. WHILE 逆向抽取进行中, THE Reverse_Modeling SHALL 仅读取 schema、元数据与节点脚本，不读取生产数据行。
7. IF 逆向建模产出的语义候选未经确定性校验与人工审批, THEN THE The_Platform SHALL 不将其写入 Semantic_Layer 单一事实源。
8. WHEN 执行任一逆向建模动作时, THE Event_Log SHALL 记录该动作的输入来源、结果与关联 `session_id`。
9. THE Reverse_Modeling SHALL 复用现有 ImportSql 前端入口与 Lineage_Service 的存量节点代码抽取能力。

### Requirement 13: 大脑/双手解耦（只读建议）

**User Story:** 作为建模工程师，我想让 LLM 只负责规划、由确定性工具执行、并以 Dev_Schema 兜底，以便在 L1 阶段获得只读的建模建议而不触碰生产。

#### Acceptance Criteria

1. THE Agent_Runtime SHALL 由 LLM_Service 产出规划与提议，由 Deterministic_Tool 与执行底座（OpenAPI_Client / MaxCompute_Client）执行。
2. WHILE 运行在 L1 阶段, THE Agent_Runtime SHALL 仅产出只读建议，不对 Prod_Schema 执行写操作。
3. WHERE agent 需要落地验证, THE Agent_Runtime SHALL 在 Dev_Schema `dataworks_dev` 中执行。
4. WHEN LLM_Service 产出 DDL 提议时, THE Root_Checker 与 DDL_Checker SHALL 对该 DDL 执行词根与命名/SQL 规范校验。
5. IF LLM 提议的 DDL 未通过词根或规范校验, THEN THE Agent_Runtime SHALL 拒绝该提议并返回校验失败原因。

### Requirement 14: 确定性校验与人工审批闸口

**User Story:** 作为数据安全负责人，我想让 LLM 生成物必过确定性校验、且建表/发布前必须人工确认，以便杜绝 LLM 直接改动生产。

#### Acceptance Criteria

1. WHEN 任一 DDL 生成后, THE The_Platform SHALL 在建表前使 Root_Checker 与 DDL_Checker 校验通过作为前置条件。
2. IF DDL 未通过 Root_Checker 或 DDL_Checker 校验, THEN THE The_Platform SHALL 阻止建表操作。
3. WHEN 建表或发布操作被请求时, THE Publish_Gate SHALL 先以 dry_run / preview 模式呈现变更内容并要求人工确认。
4. WHILE 人工确认尚未给出, THE Publish_Gate SHALL 阻止对 Prod_Schema 的建表与发布操作。
5. THE The_Platform SHALL 不允许 LLM_Service 直接触发对 Prod_Schema 的写操作。
6. WHEN Publish_Gate 触发人工审批时, THE Agent_Runtime SHALL 将其建模为 interrupt：保存 Checkpoint 状态快照、暴露中断载荷（拟执行的变更内容）、绑定权限上下文，并在收到 resume 指令后从该断点继续执行。

## L2 —— 语义知识图谱 + 无状态 agent 重放续跑

### Requirement 15: 语义知识图谱（Semantic_Graph）

**User Story:** 作为建模工程师，我想让平台把血缘、业务含义与元数据融合成语义知识图谱，以便 agent 拥有可推理的世界模型。

#### Acceptance Criteria

1. THE Semantic_Graph SHALL 融合来自 Lineage_Service 的血缘、Semantic_Layer 的业务含义与 DataWorks 元数据。
2. WHEN 给定一个表标识时, THE Semantic_Graph SHALL 返回该表的上游依赖、下游消费与关联业务口径。
3. WHEN 血缘或元数据发生更新时, THE Semantic_Graph SHALL 在下一次查询时反映更新后的关系。
4. IF 查询的实体在图谱中不存在, THEN THE Semantic_Graph SHALL 返回明确的实体不存在结果。
5. THE Semantic_Graph SHALL 支持以 Reverse_Modeling 逆向抽取的存量血缘与元数据作为其初始 bootstrap 内容。
6. WHEN 返回某表的图谱信息时, THE Semantic_Graph SHALL 附带该表的 Quality_Signal，使 agent 推理时可感知数据可信度。

### Requirement 16: 无状态 agent 与重放续跑

**User Story:** 作为平台维护者，我想让 agent 无状态并以 Event_Log 为唯一事实源，以便 agent 崩溃后可按 `session_id` 重放续跑。

#### Acceptance Criteria

1. THE Agent_Runtime SHALL 不在进程内存中保存跨请求的会话状态，会话状态以 Event_Log 为唯一事实源。
2. WHEN agent 进程崩溃后重启时, THE Agent_Runtime SHALL 依据指定 `session_id` 的 Event_Log 重建会话状态。
3. WHEN 依据 Event_Log 重建会话后, THE Agent_Runtime SHALL 从最后一个已完成步骤之后续跑该会话。
4. WHEN 重放已完成的步骤时, THE Agent_Runtime SHALL 不重复执行已成功产生副作用的操作。
5. THE Agent_Runtime SHALL 复用 `modeling_tasks` / `pipeline_tasks` 作为 Session 载体，复用 Persistent_Queue 进行 worker 调度，复用 reconciliation 进行失败恢复。

### Requirement 17: 隔离边界（明确非目标）

**User Story:** 作为平台架构师，我想明确 agent 的隔离边界不是 MicroVM / CubeSandbox 式沙盒，以便团队不在错误方向上投入。

#### Acceptance Criteria

1. THE The_Platform SHALL 不实现 MicroVM 或 CubeSandbox 式的本机代码执行沙盒。
2. THE The_Platform SHALL 以 Dev_Schema、dry_run、Publish_Gate 人工审批与 AK/SK 最小权限的组合作为 agent 的隔离边界。
3. THE Agent_Runtime SHALL 不在本机执行不可信代码，仅通过 API 调用外部服务。

## L3 —— 统一 AI 接口（自建 AK/SK MCP）+ 单 agent 端到端

### Requirement 18: 自建 AK/SK MCP Server

**User Story:** 作为外部 AI（例如 Claude）或内部编排层，我想通过带语义、权限、审计与上下文绑定的 MCP server 访问平台能力，以便安全地消费语义化数据能力。

#### Acceptance Criteria

1. THE MCP_Server SHALL 使用 Auth_Provider 的 AK/SK 鉴权访问底层 DataWorks 与 MaxCompute 能力。
2. THE MCP_Server SHALL 向调用方暴露基于 Semantic_Layer 语义的工具接口。
3. WHEN MCP_Server 收到工具调用请求时, THE MCP_Server SHALL 依据 Permission_Model（团队 / 组织编码）校验调用方对目标资源的权限。
4. IF 调用方对目标资源无权限, THEN THE MCP_Server SHALL 拒绝该调用并返回权限不足错误。
5. WHEN MCP_Server 执行任一工具调用时, THE MCP_Server SHALL 将该调用的上下文、参数与结果记录到 Event_Log。
6. THE MCP_Server SHALL 作为面向外部 AI/编排层的新增服务端能力，与 `mcp/pool.py`（平台作为客户端连接外部 data-mcp 服务，保留不删）职责不同、互不替代。

### Requirement 19: 单 agent 端到端建模与对话查询（提议-验证-审批）

**User Story:** 作为建模工程师，我想通过单个 agent 完成端到端建模与对话式查询，以便以自然语言驱动"提议-验证-审批"闭环。

#### Acceptance Criteria

1. WHEN 用户以自然语言提出建模需求时, THE Agent_Runtime SHALL 产出建模提议（DDL、DML、调度配置）。
2. WHEN 建模提议产出后, THE Deterministic_Tool SHALL 对提议执行词根、命名/SQL 规范与分层依赖校验。
3. WHILE 建模提议未通过校验或未获人工审批, THE Agent_Runtime SHALL 不对 Prod_Schema 执行建表或发布。
4. WHEN 用户以自然语言提出查询需求时, THE Agent_Runtime SHALL 基于 Semantic_Layer 口径生成查询并经 MaxCompute_Client 返回结果。
5. IF agent 生成的查询引用了 Semantic_Layer 中不存在的口径或字段, THEN THE Agent_Runtime SHALL 拒绝执行并返回未定义口径的说明。

## L4 —— Coordinator + 多专业 agent + 模型路由 + 跨域架构设计

### Requirement 20: Coordinator 与多专业 agent

**User Story:** 作为建模工程师，我想让协调器编排需求理解 / 架构 / 建模 / 治理 / 诊断 / 查询等多个专业 agent，以便处理跨域复杂任务。

#### Acceptance Criteria

1. THE Coordinator SHALL 编排需求理解、架构、建模、治理、诊断、查询等专业 agent。
2. WHEN 收到一个复杂任务时, THE Coordinator SHALL 将任务分解为子任务并分派给对应的专业 agent。
3. WHEN 专业 agent 完成子任务时, THE Coordinator SHALL 汇总子任务结果并推进整体任务。
4. WHEN Coordinator 或任一专业 agent 调用 LLM 时, THE LLM_Router SHALL 按子任务复杂度选择模型。
5. WHERE 任务涉及跨域架构设计或成本优化, THE Coordinator SHALL 在执行落地前经过 Publish_Gate 人工审批闸口。
6. IF 某个专业 agent 的子任务失败, THEN THE Coordinator SHALL 记录失败到 Event_Log 并阻止依赖该子任务结果的下游子任务执行。

## L5 —— 持续自愈 + 语义自进化

### Requirement 21: 持续自愈与语义自进化

**User Story:** 作为数据平台运营者，我想让平台具备值班级的持续自愈与语义自进化能力，以便在人工介入最小化的情况下维持数据健康。

#### Acceptance Criteria

1. WHEN 检测到调度任务失败或数据异常（含数据质量维度：新鲜度 / 完整性 / 唯一性等）时, THE Agent_Runtime SHALL 产出自愈提议并记录到 Event_Log。
2. WHERE 自愈提议涉及对 Prod_Schema 的写操作, THE Publish_Gate SHALL 在执行前要求人工审批。
3. WHEN Semantic_Layer 检测到新的口径、别名或维度关系候选时, THE Agent_Runtime SHALL 产出语义演进提议供人工确认。
4. WHILE 语义演进提议未获人工确认, THE Semantic_Layer SHALL 不将候选定义写入单一事实源。
5. THE The_Platform SHALL 将所有自愈与语义自进化行为记录到 Event_Log 以供审计。

## 非功能性需求（跨阶段）

### Requirement 22: 安全与密钥管理

**User Story:** 作为数据安全负责人，我想让所有密钥通过环境变量管理且永不进入日志，以便降低凭证泄露风险。

#### Acceptance Criteria

1. THE The_Platform SHALL 通过 `.env` 或环境变量管理 AK/SK 与 LLM_API_Key。
2. WHEN The_Platform 写入任一日志或 Event_Log 时, THE The_Platform SHALL 排除 AK/SK 与 LLM_API_Key 的明文值。
3. THE The_Platform SHALL 以当前 AK/SK 的开发环境权限为既定边界运行，不假设未来会获得 `AliyunDataWorksFullAccess` 或等价生产级权限；WHERE 后续获得更高权限, THE The_Platform SHALL 支持将 Requirement 1 中标注"长期走 Cookie"的能力重新评估迁移到 AK/SK，但不作为当前实现的前提。
4. IF 日志内容中检测到疑似密钥明文, THEN THE The_Platform SHALL 对该值做脱敏处理后再写入。

### Requirement 23: 成本可观测

**User Story:** 作为平台运营者，我想统计 LLM 的 Token 用量、成本与耗时，以便控制并归因 AI 成本。

#### Acceptance Criteria

1. WHEN 任一 LLM_Service 调用完成时, THE Cost_Monitor SHALL 记录该调用的 Token 用量、估算成本与耗时。
2. THE Cost_Monitor SHALL 支持按 `session_id` 与模型型号聚合 Token 用量与成本。
3. WHEN 请求成本统计时, THE Cost_Monitor SHALL 返回指定维度的 Token 用量、成本与耗时汇总。

### Requirement 24: 可审计性

**User Story:** 作为审计人员，我想让所有 agent 行为进入 Event_Log，以便任何操作都可追溯。

#### Acceptance Criteria

1. WHEN Agent_Runtime 执行任一提议、校验、执行或审批动作时, THE Event_Log SHALL 记录该动作的类型、发起者、目标与结果。
2. THE Event_Log SHALL 为每条记录保留时间戳与关联的 `session_id`。
3. WHEN 请求某 `session_id` 的审计轨迹时, THE Event_Log SHALL 返回该会话所有已记录动作的有序序列。
4. THE Event_Log SHALL 以 Trace / Span 的父子因果结构记录一次 Run 内的 Step、工具调用、LLM 调用与 Handoff，保留成本归因（token / 耗时）并关联到相应 Checkpoint。

## 部署与多人使用（跨阶段）

### Requirement 26: 共享服务部署形态与主语言

**User Story:** 作为平台运维者，我想把平台部署为 VPC 内单一共享服务并固定技术栈，以便团队集中使用、贴近数据源、降低运维复杂度。

#### Acceptance Criteria

1. THE The_Platform SHALL 以 Python 3.12 为后端主语言、Vue + TypeScript 为前端，沿用现有技术栈不更换。
2. THE Shared_Service SHALL 部署为 dataworks 阿里云 VPC 内的单进程单节点共享服务。
3. THE Shared_Service SHALL 以单一服务级 AK/SK 统一对接 DataWorks 与 MaxCompute。
4. THE The_Platform SHALL 沿用 SQLite（WAL 模式）作为状态存储。
5. WHERE 未来扩展为多副本部署或出现高并发写, THE The_Platform SHALL 重新评估迁移到服务端数据库（例如 RDS PostgreSQL / PolarDB）。

### Requirement 27: 多用户 IP 归属与网络访问收口

**User Story:** 作为平台运维者，我想以 IP 区分多用户并在网络层收口访问，以便在不具备 SSO 的前提下实现基本的归属、隔离与访问控制。

#### Acceptance Criteria

1. THE The_Platform SHALL 以来源 IP（IP_Identity）作为多用户任务归属与隔离依据，复用现有 IP 隔离中间件。
2. WHEN 记录任一任务或 agent 行为到 Event_Log 时, THE The_Platform SHALL 记录发起方 IP 作为归属标识。
3. THE The_Platform SHALL 在网络层限制访问来源（绑定内网地址 + 安全组 / 防火墙白名单），不将服务暴露到公网。
4. THE The_Platform SHALL 明确 IP_Identity 属软隔离而非身份认证，不将其作为对 Prod_Schema 写操作的唯一授权依据。
5. WHERE 涉及对 Prod_Schema 的写操作, THE The_Platform SHALL 仍要求经过 Publish_Gate 人工审批，不因 IP 归属而跳过。
6. WHERE 需要更强访问控制, THE The_Platform SHALL 支持叠加共享口令或后续接入 SSO，而不重构现有 IP 归属机制。
7. WHERE 请求来自 DingTalk_Adapter 或已钉钉扫码登录的 Web_UI 等可解析真实身份的渠道, THE The_Platform SHALL 优先采用 Permission_Model（团队 / 组织编码）鉴权，IP_Identity 仅作为身份不可解析时（未登录访问）的回退归属。

## 数据质量（消费 DQC + 语义化 / 智能化，跨 L3-L4）

### Requirement 28: 数据质量的语义化与智能化（消费 DQC，不重建引擎）

**User Story:** 作为数据治理负责人，我想让平台消费 DataWorks 数据质量能力的规则与结果、并由 agent 做质量诊断与规则提议，以便在不重建质量引擎的前提下让 agent 能判断数据可信度。

#### Acceptance Criteria

1. THE The_Platform SHALL 通过 OpenAPI_Client 消费 DataWorks_DQC 的质量规则与校验结果，不自建质量规则执行引擎或数据 profiling 调度。
2. WHEN 获取到某表的 DataWorks_DQC 结果时, THE Semantic_Layer SHALL 将其转化为该表的 Quality_Signal 供 agent 消费。
3. WHEN agent 对存量表执行逆向建模或诊断时, THE Agent_Runtime SHALL 由 LLM_Service 提议质量规则候选（如主键唯一性、非空约束、值域），并经 Deterministic_Tool 核验后交人工审批。
4. WHILE 质量规则候选未获人工审批, THE The_Platform SHALL 不将其写入 DataWorks_DQC。
5. IF agent 生成的查询或建模引用了 Quality_Signal 标记为不可信（过期 / 校验失败）的表, THEN THE Agent_Runtime SHALL 在结果中明确告警该数据的可信度问题。
6. THE The_Platform SHALL 不实现独立的数据质量规则引擎与数据 profiling 调度平台，该能力由 DataWorks_DQC 提供。

### Requirement 25: 演进顺序约束与资产复用

**User Story:** 作为平台架构师，我想强制"先统一底座（语义层）再上 AI"的演进顺序并复用现有资产，以便避免在旧平台上直接叠加聊天入口造成的架构失控。

#### Acceptance Criteria

1. THE The_Platform SHALL 在 Semantic_Layer（L1）尚未建立前，不启用面向生产的对话式 AI 建模入口（L3 及以上）。
2. THE The_Platform SHALL 保留并复用 `modeling/`、`governance/`、`standards/`、`naming/`、`task_engine/state_machine` 以及 FastAPI + Vue + SQLite 主体。
3. THE The_Platform SHALL 在演进中保留现有资产而非重写，无论其是否依赖 Cookie 链路——Cookie 链路本身作为长期兜底通道保留（见 Requirement 1），不构成重写资产的理由。
4. THE The_Platform SHALL 不重建统一数据、统一元数据、统一计算三层能力，该三层由 MaxCompute 与 DataWorks 提供。
5. WHEN 引入新能力时, THE The_Platform SHALL 遵循"简单优先 / 外科手术式修改"原则，不为一次性代码引入通用 agent 平台式抽象。

## Agent Runtime 协议对象与可评测性（跨阶段）

### Requirement 29: Runtime 协议对象与生命周期操作（框架无关）

**User Story:** 作为平台架构师，我想让 Agent_Runtime 对外暴露稳定的协议对象与生命周期操作、并与具体执行框架解耦，以便框架更迭时领域逻辑与外部系统不受影响。

#### Acceptance Criteria

1. THE Agent_Runtime SHALL 以 Runtime_Protocol_Object（Session、Run、Step、Event、Artifact、Checkpoint）作为对外稳定协议对象，分别复用 `modeling_tasks`/`pipeline_tasks`（Session）、执行边界（Run）、`*_step_logs`（Step）、Event_Log/SSE（Event）、`artifacts`（Artifact）与可恢复快照（Checkpoint）。
2. THE Agent_Runtime SHALL 支持对 Run 施加 stream / interrupt / resume / cancel / retry 五类生命周期操作。
3. THE The_Platform SHALL 使领域逻辑（命名 / 分层 / 词根 / 血缘 / 语义层）仅依赖上述协议对象契约，不绑定任何具体 agent 框架（如 LangGraph / Deep Agents / Claude Agent SDK）。
4. WHILE 处于 L0-L3, THE Agent_Runtime SHALL 以自建薄运行时（复用 SQLite 既有 `step_logs` / `PersistentPipelineQueue` / reconciliation 原语）实现该契约，不引入重型 agent 框架。
5. WHERE 进入 L4 多 agent 协作且自建调度不足, THE The_Platform SHALL 可在协议对象契约不变的前提下替换底层执行引擎（例如引入 LangGraph / Deep Agents）而不改动领域逻辑。
6. THE Agent_Runtime SHALL 将 Artifact 建模为可引用、可追溯到具体 Run 的一等对象。
7. WHEN 客户端订阅某 Run 的事件流时, THE Agent_Runtime SHALL 通过 SSE 提供事件流，并支持基于 Last-Event-ID 的断线续传（事件持久化后先回放 catch-up 再切换实时）。

### Requirement 30: Error-as-Data 与错误边界

**User Story:** 作为建模工程师，我想让可恢复的工具 / SQL 错误作为数据回传给 LLM 供其自主决策，而系统级 / 安全级错误走异常与审批，以便 agent 既有韧性又不失控。

#### Acceptance Criteria

1. WHEN 工具或 SQL 调用发生可恢复错误（如超时、限流、可修正的语法错误）时, THE Agent_Runtime SHALL 将错误作为结构化数据返回给 LLM_Service 供其决策重试或改写。
2. IF 发生系统级或安全级错误（Prod_Schema 写失败、权限拒绝、凭证缺失）, THEN THE Agent_Runtime SHALL 以异常中断执行并交由 Publish_Gate 或人工处理，不将其作为数据回传给 LLM 自主重试。
3. WHEN 任一错误发生时, THE Event_Log SHALL 记录错误类型、归属的 Run / Step 与处理方式。
4. WHERE 存在 Checkpoint, THE Agent_Runtime SHALL 在失败后从最近稳定 Checkpoint 恢复并仅重试失败的 Step，不重跑已成功的 Step。

### Requirement 31: 可评测性与反馈闭环

**User Story:** 作为平台运营者，我想评价 agent 产出质量、沉淀 badcase 并形成反馈闭环，以便平台越用越懂 dataworks、持续自我改进。

#### Acceptance Criteria

1. THE The_Platform SHALL 记录 agent 产出的质量指标（如 DDL 一次过校验率、逆向语义候选人工采纳率、查询口径命中率）。
2. WHEN agent 产出被确定性校验或人工审批拒绝时, THE The_Platform SHALL 将该案例结构化记录为 Badcase（含输入、产出、失败原因与归属 Run）。
3. THE The_Platform SHALL 支持基于 Event_Log 与 Badcase 库对 agent 产出质量进行归因分析。
4. WHERE 评测识别出系统性问题, THE The_Platform SHALL 支持将结论反馈用于 prompt、工具或规范（Standards_Bundle / Semantic_Layer）的迭代。
5. THE The_Platform SHALL 不将生产数据行纳入评测样本，评测仅基于 schema / 元数据与 agent 行为记录。

## 指标归因诊断与业务反馈接入（L1-L3 起，跨阶段）

### Requirement 32: 指标归因诊断（业务反馈异常）

**User Story:** 作为数据工程师 / 分析师，我想让 agent 对业务反馈的指标异常做归因诊断，以便快速区分口径误解、真实波动、数据 bug、上游延迟与重复丢失，而不必每次手工沿链路排查。

#### Acceptance Criteria

1. WHEN 收到一个 Anomaly_Report 时, THE Agent_Runtime SHALL 首先基于 Semantic_Layer 澄清业务预期口径与指标实际口径的差异。
2. IF 异常可由口径差异解释, THEN THE Agent_Runtime SHALL 返回口径澄清结论而不进入数据下钻。
3. WHERE 口径一致但数值仍存疑, THE Agent_Runtime SHALL 沿 Lineage_Service 血缘逐层（DMR → DWS → DWD → ODS → 源）用 MaxCompute_Client 取聚合值比对，定位数值开始偏离的层。
4. THE Agent_Runtime SHALL 将根因分类为「口径误解 / 真实业务波动 / 数据 bug / 上游延迟或缺失 / 重复或丢失」之一，并给出证据链。
5. THE 数值比对 SHALL 由 Deterministic_Tool（pyodps 查询）执行，仅将「偏离层 / 偏离量 / 方向」等结论提供给 LLM_Service，不将原始业务数值批量发送给外部 LLM。
6. WHERE 诊断指向可修复的数据 bug, THE The_Platform SHALL 产出修复提议并经 Publish_Gate 人工审批后执行，不自动改动生产。
7. WHEN 一次归因诊断完成时, THE The_Platform SHALL 将异常、根因与处置沉淀到异常知识库（复用 Badcase 与 Event_Log），供同类异常复用。
8. WHERE 涉及归属阶段, THE Metric_Attribution 的口径澄清与只读诊断 SHALL 在 L1-L3 可用，自动处置留待 L5。

### Requirement 33: 钉钉群业务反馈接入（DingTalk_Adapter）

**User Story:** 作为业务用户，我想在钉钉群里 @机器人 反馈指标异常并得到诊断回复，以便沿用现有沟通习惯而无需切换系统。

#### Acceptance Criteria

1. THE DingTalk_Adapter SHALL 接收钉钉群中 @机器人 的消息并解析为 Anomaly_Report（指标、时间、维度、预期）。
2. IF Anomaly_Report 信息不完整, THEN THE Agent_Runtime SHALL 在同一会话中追问缺失要素后再进入诊断。
3. WHEN 诊断产出只读结论（口径澄清 / 根因报告）时, THE DingTalk_Adapter SHALL 将结论回帖到群。
4. THE DingTalk_Adapter SHALL 复用钉钉发送者身份，经 Permission_Model 解析其内部用户 / 团队 / 组织编码作为该 Anomaly_Report 的归属，并记录到 Event_Log。
5. THE The_Platform SHALL 不通过钉钉消息直接触发对 Prod_Schema 的写操作，修复一律经 Publish_Gate 审批。
6. WHEN 向钉钉群回帖时, THE The_Platform SHALL 仅返回请求方团队 / 组织编码有权访问的诊断结论与必要聚合值，不批量回传明细数据行。
7. WHERE 未来接入其他反馈渠道, THE The_Platform SHALL 以渠道适配器形式扩展而不改动 Metric_Attribution 核心流程。

## 身份与权限（跨阶段）

### Requirement 34: 身份解析与团队 / 组织编码鉴权（Permission_Model）

**User Story:** 作为数据安全负责人，我想基于钉钉身份解析出团队与组织编码并据此授权，以便在无 SSO 的前提下实现真实的按团队 / 组织的数据权限控制。

#### Acceptance Criteria

1. THE The_Platform SHALL 基于 User_Directory（钉钉用户表 join 内部用户表）将钉钉用户解析为内部用户及其团队与组织编码。
2. WHEN 通过 DingTalk_Adapter 收到 Anomaly_Report 时, THE The_Platform SHALL 解析发送者身份并确定其团队与组织编码。
3. THE Permission_Model SHALL 依据团队与组织编码决定请求方可访问的数据范围与可执行操作。
4. IF 请求方所属团队 / 组织编码无权访问目标数据或操作, THEN THE The_Platform SHALL 拒绝该请求并返回权限不足。
5. WHEN MCP_Server、对话查询（Requirement 19）或指标归因（Requirement 32）执行时, THE The_Platform SHALL 应用同一套 Permission_Model 授权。
6. WHEN 记录到 Event_Log 时, THE The_Platform SHALL 记录解析出的内部用户、团队与组织编码作为归属。
7. THE Web_UI SHALL 通过钉钉扫码登录获取钉钉身份并经 User_Directory 解析团队 / 组织编码，与 DingTalk_Adapter 共享同一 Permission_Model。
8. WHERE 用户未登录且身份无法解析, THE The_Platform SHALL 回退到 IP_Identity 归属（Requirement 27）并仅授予受限的只读能力。

## 多渠道接入（Access Surfaces，跨阶段）

### Requirement 35: 多渠道接入与统一核心

**User Story:** 作为平台使用者，我想通过与自己角色匹配的入口使用平台（工程师用 Web、业务用钉钉 / 帆软、系统用 MCP），以便各类用户以最低门槛消费同一套语义与治理能力。

#### Acceptance Criteria

1. THE The_Platform SHALL 以统一核心（Semantic_Layer + Permission_Model + Event_Log + 确定性护栏 + Agent_Runtime）服务所有接入渠道，各渠道以适配器形式接入。
2. THE Web_UI SHALL 面向数据工程师提供建模、预览、审批、血缘、治理与产物管理，并支持钉钉扫码登录获取身份。
3. THE DingTalk_Adapter SHALL 面向业务用户提供指标异常反馈与对话式问数 / 口径澄清。
4. THE MCP_Server SHALL 面向外部 AI 与内部编排层提供程序化工具调用。
5. THE FineReport_Adapter SHALL 面向帆软报表用户提供从报表上下文发起指标异常诊断的入口，并以 Semantic_Layer 作为报表口径的对齐基准。
6. WHEN 新增接入渠道时, THE The_Platform SHALL 以渠道适配器扩展而不改动统一核心。
7. WHERE 涉及对 Prod_Schema 的写操作与审批, THE The_Platform SHALL 在 Web_UI 完成人工确认，其他渠道不直接执行生产写。
8. WHEN 任一渠道发起请求时, THE The_Platform SHALL 统一应用 Permission_Model 鉴权、Event_Log 审计与数据边界约束。

## 破坏性操作防护（跨阶段·硬约束）

### Requirement 36: 禁止执行删除数据、删表与删任务（可生成不可执行）

**User Story:** 作为数据安全负责人，我想让平台在执行层拦截删除数据、删表与删除调度任务的操作，同时仍允许 agent 生成并预览这类代码，以便杜绝不可逆损失又不妨碍人工评审与手工处置。

#### Acceptance Criteria

1. THE The_Platform SHALL 不执行 DELETE 与 TRUNCATE 语句。
2. THE The_Platform SHALL 不执行针对非 `tmp_` / `test_` 前缀表的 DROP TABLE。
3. THE The_Platform SHALL 默认不执行 DROP PARTITION 与 ALTER TABLE ... DROP COLUMN。
4. THE The_Platform SHALL 不执行调度任务 / 节点的删除或下线操作（如 DeleteNode / 节点下线）。
5. WHERE 使用 INSERT OVERWRITE 作为标准 ETL 写入, THE The_Platform SHALL 允许执行，但对 Prod_Schema 须经 Publish_Gate 审批并记录到 Event_Log。
6. THE The_Platform SHALL 允许 agent 生成、预览并作为 Artifact 输出包含上述被禁止操作的代码，仅在执行层拦截，不在生成 / 提议 / 校验层因其为破坏性而拒绝。
7. THE MaxCompute_Client 与 OpenAPI_Client SHALL 在执行提交前经 DestructiveOpGuard 校验，拦截被禁止的破坏性执行（含任务 / 节点删除）并返回拒绝、不予执行。
8. WHEN 拦截到破坏性执行请求时, THE Event_Log SHALL 记录该拦截事件、语句 / 操作摘要与来源渠道。
9. THE MCP_Server SHALL 不提供以执行删除数据 / 删表 / 删任务为目的的工具，但可提供生成或预览这类代码的工具。

## Loop Engineering 基础设施

### Requirement 37: 任务闭环验收机制

**User Story:** 作为建模工程师，我想让每个建模任务完成后自动跑一组客观验收检查（DDL规范、词根校验、SQL语法、测试），以便任务完成的判定从"人看一眼觉得行了"变成"全绿才算完"。

**背景**：参考 Loop Engineering 理念，Closed Loop 能成立的关键是"验收是客观的"——测试、typecheck、benchmark 给的是硬信号，要么全绿，要么有红，没有"差不多"。Agent 不用猜"我做完了没""够不够好"，那个判断被外包给了一套确定性检查。

#### Acceptance Criteria

1. THE The_Platform SHALL 为每种建模任务类型（ODS/DWD/DIM/DWS）定义明确的验收检查清单。
2. THE The_Platform SHALL 在任务执行完成后自动运行验收检查，不依赖人工触发。
3. THE The_Platform SHALL 将验收结果（通过/失败 + 失败原因）持久化到 Event_Log。
4. IF 验收检查全绿 THEN The_Platform SHALL 标记任务为 `verified` 状态。
5. IF 验收检查有红 THEN The_Platform SHALL 标记任务为 `needs_fix` 状态，并记录具体失败项。

**验收检查清单（按任务类型）：**

| 任务类型 | 验收检查项 |
|----------|------------|
| ODS | DDL命名规范 + 词根校验 + Holo SQL语法 + DML完整性(from/where/;) |
| DWD | DDL命名规范 + 词根校验 + SQL语法(sqlglot) + 层间依赖校验 + pytest |
| DIM | DDL命名规范 + 词根校验 + SQL语法 + 日全量调度参数 + pytest |
| DWS | DDL命名规范 + 词根校验 + SQL语法 + 层间依赖校验 + pytest |

### Requirement 38: 任务 Memory 持久化

**User Story:** 作为系统维护者，我想让每个任务的进展、决策、产物都持久化到 SQLite（而非仅存在于对话上下文中），以便任何 Agent 在任何时间都能读取"现在到哪儿了"。

**背景**：参考 Loop Engineering 理念，Memory 不在对话里，循环才稳得住。把进度写进对话之外——写进文件、写进一份结构化的状态记录，让它独立于任何一次对话而存在。下一轮不管换哪个 Agent 来跑，都能读到"现在到哪儿了"。

#### Acceptance Criteria

1. THE The_Platform SHALL 在每次任务状态变更时写入 Event_Log（已有 `runs`/`events` 表）。
2. THE The_Platform SHALL 为每个任务维护一份结构化的 `task_memory` 记录，包含：
   - `progress`: 当前进度（已完成步骤列表）
   - `decisions`: 关键决策记录（为什么选这个方案）
   - `artifacts`: 产出物引用（DDL/DML/节点ID等）
   - `next_steps`: 下一步建议（供 Orchestrator 或下一轮读取）
   - `blockers`: 当前阻塞项
3. THE The_Platform SHALL 在任务完成时自动生成 `next_steps`（如：ODS建完→建议推DML）。
4. THE The_Platform SHALL 允许任何 Agent 通过 `session_id` 读取任务 Memory。

### Requirement 39: 任务自动接力

**User Story:** 作为建模工程师，我想让一个任务完成后自动触发关联的下一个任务（如ODS节点创建完成→自动推DML），以便我不需要手动逐个触发。

**背景**：参考 Loop Engineering 理念，Self-prompting 是把人彻底从接力位置上请出去的关键——上一轮跑完之后，不由人来想"下一步该问什么"，而是让 Agent 根据已有进展，自己写下一轮要跑的 Prompt。

#### Acceptance Criteria

1. THE The_Platform SHALL 定义任务接力规则（Task Chaining Rules）：
   - ODS节点创建完成 → 触发DML推送
   - DML推送完成 → 触发调度参数配置
   - 调度参数配置完成 → 触发依赖配置
   - 依赖配置完成 → 触发验证检查
2. THE The_Platform SHALL 在接力触发前检查前置任务的验收状态（必须是 `verified`）。
3. THE The_Platform SHALL 支持配置接力规则的启用/禁用（避免自动触发不适合的场景）。
4. THE The_Platform SHALL 在 Event_Log 中记录每次接力触发的决策依据。
