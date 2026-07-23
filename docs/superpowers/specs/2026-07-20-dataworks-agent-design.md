# DataWorks Agent 设计 Spec

日期:2026-07-20
状态:已确认 v0.2(`anomalyco/opencode` 活跃上游架构)

---

## 1. 背景与目标

构建一个**通用 DataWorks Agent**:Web 形态、多用户,通过自然语言操作阿里云 DataWorks / MaxCompute / ODPS / MCP 转发服务,同时保留 AI Coding Agent 的完整能力(读/写/运行本地代码)。直接 fork 当前活跃的 [`anomalyco/opencode`](https://github.com/anomalyco/opencode),保留其 Bun/TypeScript/Effect runtime、Session、Provider、工具、SDK 与 SolidJS Web 应用；DataWorks 能力以 workspace package、插件工具和独立数据适配器的方式扩展,避免重写 OpenCode 核心。

上游基线固定为 `anomalyco/opencode@cd46f22d513d60b7a9bdca1111d25c50d2398355`(2026-07-19,MIT)。以 `upstream` remote 持续同步 `dev`,所有 DataWorks 定制尽量限制在新增 package/API group/页面和少量明确的注册点。

不依赖现有 `E:\dw-agent`(giikin 内部 data-mcp/cookie 逻辑)。

## 2. 总体架构

```
┌────────────────────────────────────────────┐
│ OpenCode Web (SolidJS + Vite + Tailwind)   │
│ Chat / Files / Sessions / DW / Knowledge   │
└────────────────────┬───────────────────────┘
                     │ Same-origin HTTP/WS + HttpOnly Cookie
┌────────────────────▼───────────────────────┐
│ DataWorks Control Plane (Bun + TS + Effect)│
│ - 登录/用户/DataConnection/知识库/审计      │
│ - OpenCode HTTP/WebSocket 反向代理          │
│ - 每用户 worker 生命周期与配额              │
└──────┬──────────────────────────┬──────────┘
       │ loopback + internal token│
┌──────▼────────────────┐  ┌──────▼───────────────┐
│ OpenCode worker/user A│  │ OpenCode worker/user B│
│ 独立 data/config/root │  │ 独立 data/config/root │
│ Session/Tools/Provider│  │ Session/Tools/Provider│
│ DataWorks plugin      │  │ DataWorks plugin      │
└──────────┬────────────┘  └──────────┬────────────┘
           │ internal API             │
┌──────────▼──────────────────────────▼─────┐
│ @dataworks-agent/dataworks                │
│ OpenAPI SDK / PyODPS sidecar / MCP / RAG │
└───────────────────────────────────────────┘
```

### 2.1 代码布局

详见 [README.md](../../README.md)。

## 3. 领域与隔离模型

```
User
 ├── Worker(独立 OpenCode data/config/root)
 │    └── Code Project(OpenCode 原生 Project/Workspace)
 │         └── Session
 │              └── Message / Part / Tool Call
 └── DataConnection(一组本地加密的阿里云凭证)
      └── DataWorks Project/Space
```

- `DataConnection` 是 DataWorks 凭证隔离边界；不用 `Workspace` 命名，避免与 OpenCode 的 VCS Workspace 冲突。
- 控制面使用独立 `<app-data>/control.sqlite` 保存用户、浏览器 Session、DataConnection 元数据、审计与知识库元数据；不修改或混用每用户 OpenCode SQLite。
- 控制面 schema 通过有序 SQL migrations 升级,已应用 migration 记录 SHA-256,禁止篡改历史 migration。
- 每个用户独享一个按需启动的 OpenCode worker；多用户/生产模式的 worker 必须运行在 OCI 容器沙箱中,控制面只通过私有容器网络访问并使用随机内部密码。
- 原生进程 worker 仅用于绑定 `127.0.0.1` 的单用户开发模式；配置第二个用户、非 loopback 监听或 production 环境时拒绝启动。
- Session 元数据保存 `active_connection_id` 与 `active_dw_project_id`，工具调用以当前登录用户 + Session 元数据解析数据连接。
- 容器只挂载该用户的数据目录和管理员批准的项目根目录；不挂载宿主 HOME、SSH/AWS/系统配置目录。

## 4. 请求/响应数据流(OpenCode HttpApi/Event stream)

```
SolidJS 前端
  │ Same-origin 请求 + HttpOnly `dwa_session`
  ▼
DataWorks Control Plane
  │ 验证用户 → 解析/启动该用户 worker → 注入内部 Basic auth
  │ DataWorks/Knowledge API 留在控制面
  │ OpenCode HTTP/WS 原样代理到该用户 worker
  ▼
OpenCode SessionV2 / ToolRegistry
  │ 构造 prompt:
  │   - System: 注入 DataConnection/DataWorks Project 元数据 + 已加载 Skill 摘要 + 安全规则
  │   - Tool Schema: Coding + DataWorks
  │ 调 LLM(streaming)
  │
  │  LLM 返回 tool_call → OpenCode ToolRegistry 调度 →
  │      Coding 工具 → OpenCode 原生实现
  │      dw_* 工具    → @dataworks-agent/plugin
  │                       → DataWorks Control Plane(凭证 + 限流 + 审计)
  │                       → DataWorks OpenAPI SDK / PyODPS sidecar / MCP
  │
  │  工具结果回填 → LLM 继续 → ... → 最终回复
  ▼
OpenCode 原生事件流回前端:
  - Session/Message/Part 事件
  - permission.asked / permission.replied
  - tool 状态与流式文本 part
  - error / session.idle
```

事件协议直接使用 OpenCode 的生成式 SDK/EventManifest,新增公共 HttpApi 后运行 `bun run generate` 生成客户端,不维护第二套手写 SSE 枚举。

## 5. DataWorks 工具集

按"高频 → 低频"分层,**所有工具前置声明权限级别**,控制面在执行前再校验一次当前用户、DataConnection 与一次性票据,防止 LLM/worker 越权。

| 工具 | 权限级 | 描述 |
|---|---|---|
| `dw_list_projects` | read | 列出当前账号可见的 DataWorks 项目 |
| `dw_list_tables` | read | 按 schema/关键词搜表 |
| `dw_describe_table` | read | 表结构/分区/生命周期/词根 |
| `dw_run_sql` | read | ODPS SQL 受限查询(默认 5min 超时、10000 行结果集上限;具体限额在 DataConnection 配置可调) |
| `dw_run_sql_full` | read+high | 走 MCQA 的大结果集查询(默认 30min、100 万行上限;需 `allow_full_sql=true`) |
| `dw_table_lineage` | read | 上下游血缘(封装 OpenAPI) |
| `dw_list_jobs` | read | 列作业/任务 |
| `dw_get_job_status` | read | 作业实例状态 |
| `dw_rerun_job` | **write** | 重跑作业实例 |
| `dw_trigger_supplement` | **write** | 触发补数据 |
| `dw_pause_schedule` | **write** | 暂停/恢复调度 |
| `dw_alert_list` | read | 运维告警列表 |
| `dw_alert_silence` | **write** | 静默告警 |
| `dw_mcp_call` | read | 转发到任意 MCP(透传) |

**写操作默认关闭**:`DataConnection.write_enabled=false` 时,所有 write 工具被 `PermissionV1` 隐藏/拒绝。开启后仍必须触发 OpenCode `permission.asked`,前端二次确认并填写原因；控制面记录审计日志后才签发一次性执行票据。

## 6. 认证与凭证隔离

- v0 登录:本地账号 + `@node-rs/argon2@2.0.2` Argon2id 密码哈希 + 32B 随机 Session token。
- 浏览器只保存 `HttpOnly; SameSite=Lax; Secure(生产)` 的 `dwa_session` Cookie；数据库只保存 token 的 SHA-256 hash。
- 所有变更类控制面 API、OpenCode 代理请求和 WebSocket upgrade 都校验精确 `Origin`;无 `Origin` 时要求 `Sec-Fetch-Site=same-origin|none`,不允许带凭证的通配 CORS。
- 管理员创建用户；公开注册默认关闭。统一 `AuthProvider` 接口为后续钉钉 OAuth/企业 SSO 留扩展点。
- DataWorks 凭证以 `AccessKey ID` 为标识加密保存,绑定到 `DataConnection`。
- 多个 DataConnection 可对应多个阿里云账号；凭证不写入 OpenCode 配置、Session、日志或前端状态。
- v0 **不**走 STS / RAM Role；后续可在相同 CredentialProvider 接口下增加。

凭证加密详见 §7.2。

## 7. 私有文件 / 知识库 / Skill / RAG 本地保护

### 7.1 本地路径布局

```
<app-data>/
├── config/                         # 非秘密配置与 KDF 元数据
├── secrets.dat                     # AES-GCM 加密:AK、LLM Key、MCP Token
├── users/{user_id}/
│   ├── home/                       # 独立 OpenCode HOME
│   ├── data/                       # 独立 XDG_DATA_HOME/Session/SQLite
│   ├── config/                     # 独立 XDG_CONFIG_HOME/Skill
│   ├── cache/
│   └── knowledge/
│       ├── documents/
│       └── index/                  # LanceDB
├── skills/system/                  # 管理员注入,普通用户只读
├── logs/
│   ├── audit.log
│   ├── session.log
│   └── error.log
└── cache/
```

`<app-data>` 由平台目录 API 解析:Windows 使用 `%APPDATA%\\dataworks-agent`,Linux/macOS 使用 XDG data/config 目录。系统 keyring 中只保存服务 `dataworks-agent` / 账号 `master-key-v1` 的主密钥,**没有 `.keyring` 文件**。

**全部不进仓**:`.gitignore` 覆盖 `data/`、`secrets.dat`、`*.dat`、`.keyring`、SQLite/LanceDB 和日志文件;即使开发者误把运行目录放在仓库内也不会提交。

### 7.2 凭证加密

`secrets.dat` 格式:

```
header(16B): magic "DWA\0SECRETSv1\0\0\0"
nonce(12B)
ciphertext(AES-256-GCM):
  {
    "version": 1,
    "items": {
      "connection:abc/aliyun_ak": "...",
      "connection:abc/aliyun_sk": "...",
      "provider:openai/api_key": "..."
    }
  }
```

- **KDF/密钥保护**:32B 主密钥由系统凭据库保护,应用只保存不可逆的凭据引用。
- **系统凭据库**:`@napi-rs/keyring@1.3.0`,映射到 Windows Credential Manager、macOS Keychain、Linux Secret Service。
- 无系统凭据库时 fallback:Argon2id 口令派生;仅保存 salt/KDF 参数,不保存口令 hash 充当密钥。
- `secrets.dat` 采用 AES-256-GCM,每次写入使用新 nonce;启动按需解密,秘密值用 `Redacted` 包装并禁止日志序列化。

### 7.3 Skill 系统

Skill 形态:单目录 = 一个 Skill。所有元数据集中在 `SKILL.md` 的 frontmatter,不再单独 `skill.toml`(避免双源同步)。

```
skills/{skill_name}/
├── SKILL.md                # frontmatter(元数据 + 权限) + 正文(给 LLM 看的领域知识)
└── (可选) tools/           # 关联的辅助资源(SQL 片段/示例查询),非可执行代码
```

> 仅借鉴 `data-aid` 的 **目录化 + 元数据文件** 形态(data-aid 是 Flask + MySQL,本项目是 Bun/TypeScript + Python sidecar,**不**复制其代码)。

```yaml
---
name: logistics-anomaly
description: 物流异常订单根因排查
triggers: ["物流异常", "查物流", "order_anomaly"]
allowed_tools: [dw_run_sql, dw_list_tables, dw_describe_table]
forbidden_tools: [dw_rerun_job, dw_trigger_supplement]
max_tool_calls_per_session: 20
write_enabled: false
---
```

**安全护栏**:
- 复用 OpenCode `Skill.Service` 与 `SkillTool`,不实现第二套 Skill runtime。
- DataWorks frontmatter 由独立 loader 扩展并转换成 OpenCode `PermissionV1.Ruleset`;所有 `dw_write_*` 权限默认 `ask` 或 `deny`。
- Skill 文件修改后由 OpenCode 配置/文件监控刷新实例上下文。
- 管理员 Skill 走 `skills/system/`(只读);用户 Skill 走 `skills/user/{user_id}/`。
- 前端:管理员看到全部,普通用户只看自己有权限 + system。

### 7.4 RAG(文档摄入 + 向量检索)

- **存储**:原文 + 元数据沿用 OpenCode SQLite/Drizzle;向量索引 `@lancedb/lancedb@0.31.0`(本地嵌入式)。
- **Embedding**:`EmbeddingProvider` 接口,支持离线 FastEmbed、本地测试 embedding、OpenAI-compatible 与 DashScope。离线模型必须由固定 manifest 声明 model ID/revision/license/SHA-256,在构建期下载校验,运行时禁止隐式联网下载。
- 每个知识库声明 `egress_policy=local_only|approved_providers`;默认 `local_only`。
- `local_only` 文档只能使用本地 embedding/本地 LLM,不得注入远程 Provider 请求；切换到远程 Provider 时前端明确提示并要求用户为该知识库授权。
- **分块**:递归字符切块,512 token,overlap 64。
- **摄入 API**:`POST /api/knowledge/upload`,支持 pdf/docx/md/txt;50MB/文件,1000 页上限。
- PDF/DOCX 解析在无网络、限 CPU/内存/时间/输出大小的独立 parser worker 中执行；解析失败只影响当前文档,不拖垮控制面。
- **检索 API**:`POST /api/knowledge/search`(top_k=10, similarity threshold)。
- **隔离**:强制 user_id 绑定;管理员代理检索审计双写。
- **降级**:LLM 不可用时,本地检索仍可返回 chunk 列表;索引损坏自动 rebuild。

### 7.5 运行时文件与进程沙箱

- 多用户/生产 worker 使用 OCI 容器:非 root、只读 rootfs、`cap-drop=ALL`、`no-new-privileges`、默认 seccomp、PID/内存/CPU 限制、非 host 网络。
- 容器只挂载 `users/{user_id}` 与管理员批准的项目根；临时目录使用限额 tmpfs。宿主 HOME、SSH/AWS、控制面数据库、`secrets.dat` 和其他用户目录在容器内不存在。
- worker HTTP(S) 出网经控制面 allowlist proxy；仅允许已配置 LLM Provider 域名和管理员批准的软件源,阻断 loopback/link-local/RFC1918/云元数据地址(控制面内部服务使用独立不可伪造路由与 worker token)。
- 原生单用户开发模式仍使用 OpenCode `PermissionV1`、`external_directory` 和 `read/edit/write/apply_patch/shell` 入口的强制私有目录 deny。
- 使用 `path.resolve` + `fs.realpath` 校验,防 `..` 与符号链接/junction 逃逸；强制 deny 不能由用户的 `always` 授权覆盖。

### 7.6 前端凭证零接触

- 前端调 `/api/data-connections` 与 `/api/dataworks/*` 只接收脱敏字段(账号 ID 末四位、project 名)。
- `display_ak = ak[:6] + "***" + ak[-4:]`(已登录用户可见,不可复制)。
- AK/SK 永远不通过 OpenCode 事件流到前端。

## 8. LLM Provider 与数据出站保护

- OpenCode Provider 的非秘密配置继续使用其 JSON/JSONC 配置体系;控制面的非秘密配置由 Effect Config/环境变量加载。
- 多用户模式下 LLM API Key/OAuth token 与 DataWorks Secret 都只存控制面 `secrets.dat`;worker 不持有真实 Provider 凭证。
- worker 只持有短期、绑定 user/worker/audience 的内部令牌,OpenCode Provider base URL 指向控制面流式 LLM Gateway；Gateway 根据已授权 Provider 注入真实凭证。
- LLM Gateway 透传流式请求/响应但执行模型 allowlist、请求体上限、超时、审计和数据出站策略；日志不记录 prompt/response 正文。
- OpenCode 原生 Provider OAuth 登录仅在单用户开发模式开放；多用户模式在对应 OAuth broker 完成前禁用,不允许 token 落入 worker data/config。
- Provider 切换复用 OpenCode 前端的模型交互,连接/凭证管理由 DataWorks 控制面页面完成。
- 项目目录与知识库分别声明数据出站策略。默认 `prompt_only`:只发送用户显式加入 prompt 的内容；`local_only` 禁止远程 LLM/embedding；`approved_providers` 仅允许指定 Provider。
- 前端在首次把文件、表结果或 RAG chunk 发给远程 Provider 前展示数据类别、目标 Provider 与持久化选择；选择和后续变更写审计日志。
- 工具结果默认先结构化/截断/脱敏再返回模型；大结果集、原始凭证、控制面日志和其他用户数据禁止进入 LLM 上下文。

## 9. 前端(OpenCode Web + new-api 视觉语言)

### 9.1 技术栈

- **保留上游**:SolidJS 1.9 + TypeScript + Vite 7 + Tailwind CSS 4
- **应用/UI**:`packages/app` + `packages/ui`,不改写为 React
- **路由**:`@solidjs/router`
- **服务调用**:OpenCode 生成式 SDK + `@tanstack/solid-query`
- **状态/同步**:复用 OpenCode context/store/event stream
- **Markdown/代码高亮**:OpenCode `marked` + `marked-shiki` + Shiki
- **i18n**:复用 OpenCode `@solid-primitives/i18n`
- **视觉参考**:只借鉴 `QuantumNous/new-api` 的 OKLCH token、后台信息密度、圆角与明暗主题,不复制其 React 代码、品牌或受保护标识

### 9.2 主题 Token(对照 newapi 的 theme.css 体系,**不复制版权头**)

- **字体**:英文 sans = Public Sans;serif 选项 = Lora;中文走系统字体兜底(PingFang/Noto/Microsoft YaHei)。
- **色空间**:OKLCH。
- **亮色主题**:背景白;主色蓝(OKLCH 0.69/0.14/244°);边框/分隔线 OKLCH 0.93 中性灰;文字 OKLCH 0.145。
- **暗色主题**:背景炭灰(OKLCH 0.235);主色稍深蓝;边框半透明白(OKLCH 1/0%/10%)。
- **状态色**:success(绿 OKLCH 0.6/0.145/163)、warning(橙 OKLCH 0.68/0.162/76)、destructive(红 OKLCH 0.577/0.245/27)、info(蓝)、neutral(灰)。
- **圆角**:基础 `--radius: 1rem`,成比例扩展 sm/md/lg/xl/2xl/3xl/4xl(0.6/0.8/1.0/1.4/1.8/2.2/2.6 倍)。
- **侧边栏**:`--sidebar-*` 独立 token 组,与主区分离。
- **表格**:`--table-row / --table-header / --table-disabled*` 单独定义,subtle 风格。
- **暗色切换**:`@custom-variant dark (&:is(.dark *))` + `next-themes`。

### 9.3 关键页面

- **登录页**:单列居中,大号品牌 + Provider/账号/工作区切换。
- **侧边栏**:常驻左侧,workspace 切换、Session 列表、Skill 管理、Knowledge 管理、Settings。
- **主区**:Chat 区域为主,顶部栏显示当前 workspace + project + 当前 Session 信息。
- **表格**:复用 `packages/ui` 的表格/列表基础组件,新增 DataWorks 项目/表/作业/告警视图的搜索、筛选和分页。
- **卡片**:Overview 仪表盘(用量、活跃 Session、Top 表、Top 作业)。
- **写操作二次确认**:Modal + 必填原因(写入 audit.log)。

## 10. 测试与验收策略(集成测试为主)

```
tests/integration/
├── dataworks-openapi.test.ts       # 真 DataWorks staging
├── pyodps-sidecar.test.ts          # Bun ↔ PyODPS JSON-RPC
├── dataworks-tools.test.ts         # ToolRegistry + dry-run/真实 adapter
├── auth-session.test.ts            # 多用户 Cookie 与隔离
├── skill-rag.test.ts               # Skill 热加载 + RAG 用户隔离
└── web-dataworks.spec.ts            # Playwright 关键流程
```

- CI 矩阵:
  - `unit` 全部 PR 跑;
  - `integration/*` 仅 `main` / release 分支跑(需 staging 凭证,GitHub Secret 注入);
  - `web_e2e` 同上。
- 本地:`DATAWORKS_AGENT_DRY_RUN=1` dry-run 模式,工具返回 `tests/fixtures/` 下的真实响应样本(脱敏),不调用真实云。
- **不堆单测**:每个新工具至少 1 个集成测试覆盖真凭证/真 SDK/真 HTTP 行为,验收要看 staging 跑过的截图/日志。

## 11. 提交与项目治理

### 11.1 提交规范

- **Conventional Commits**:`feat:` / `fix:` / `refactor:` / `docs:` / `test:` / `chore:` / `perf:`。
- 每个 commit 一个明确意图;大改动拆 PR。
- `main` 受保护:必须 PR + CI 通过 + 至少 1 评审。

### 11.2 分支策略

- `main`:稳定分支,tag 走语义化版本(`v0.1.0` / `v0.2.0`)。
- `<scope>-<short-desc>`:工作分支,最多 3 个短横线分隔词,不使用 `/`(对齐 OpenCode 上游约定)。
- `upstream-sync`:只用于合入 `upstream/dev`,通过独立 PR 进入 `main`。
- `release-vX.Y.Z`:发布准备,只允许文档、版本与发布修复。
- 合并策略:**Squash merge**;功能分支允许频繁小提交,`main` 保持一 PR 一 Conventional Commit。

### 11.3 PR 模板

放在 `.github/PULL_REQUEST_TEMPLATE.md`,包含:
- 改了什么、为什么;
- 影响的模块;
- 验证步骤(本地 dry-run + staging 截图);
- 风险与回滚;
- 测试清单。

### 11.4 版本与 CHANGELOG

- `release-please` 自动生成 `CHANGELOG.md`,基于 Conventional Commits。
- `VERSION` 文件由 release-please 更新。

### 11.5 集成测试 vs 单测

- 单测**只覆盖**:
  - 解析器、序列化器
  - 限流算法
  - 路径白名单匹配
  - secrets 加解密正确性
- 任何启用的 DataWorks 写工具必须在发布 staging 环境有专用、可恢复的真实验收；不能用 dry-run 代替。

### 11.6 验收标准

- **真实 staging 跑通**:每个影响 DataWorks/ODPS 行为的 PR 提供 staging 日志/截图；发布门禁必须逐项验证所有启用的读写工具。写工具只操作专用 no-op 作业/测试调度/测试告警并恢复初始状态；未执行写测试不得把 release staging gate 标为通过。
- **必填验收清单**:
  - [ ] dry-run 通过
  - [ ] DataWorks/ODPS 集成测试 staging 通过
  - [ ] 所有启用写工具在专用 staging fixture 验证并恢复初始状态
  - [ ] 关键路径 web_e2e 截图
  - [ ] `dataworks_agent start` 能在开发机本地起
  - [ ] `secrets.dat` 加密 + 解密往返
  - [ ] 文档已更新(README/AGENTS.md/CHANGELOG)

## 12. 不做(YAGNI)

v0 **不**做:
- STS / RAM Role 轮换
- 移动端 / 小程序
- 多租户计费
- 公开 SaaS 化部署
- 商业 LLM API 之外的私有模型训练
- 表血缘图可视化大屏(只做列表)
- 大结果集导出(只导出 csv,最大 10MB)

## 13. 风险与缓解

| 风险 | 缓解 |
|---|---|
| OpenCode worker 可执行任意 shell,进程级 HOME 隔离不足 | 多用户/生产强制 OCI 沙箱,只挂载该用户与批准项目目录;原生进程仅限 loopback 单用户开发 |
| worker 可通过 shell 读取自身 Provider 凭证 | 多用户模式不向 worker 下发真实 LLM Key/OAuth token;统一经控制面 LLM Gateway 注入,worker 只持短期内部令牌 |
| 远程 LLM/embedding 可能带走私有代码和知识库 | 默认 `prompt_only`/`local_only`,按 Provider 显式授权,出站代理 allowlist,工具结果脱敏/截断,选择写审计 |
| OpenCode 上游改动频繁,fork 维护成本高 | 固定基线 SHA;只新增 workspace package/API group/页面,核心注册点改动控制在少量文件;每月 `upstream-sync` PR 跑全套类型检查、HttpApi exercise 与浏览器 E2E |
| MaxCompute 无等价官方 Node/Bun 查询 SDK | Bun 主进程管理常驻 PyODPS JSON-RPC sidecar;协议有超时、取消、行数上限和崩溃重启;MCP 作为可选降级 |
| 阿里云 OpenAPI 鉴权复杂 | 固定官方 `@alicloud/dataworks-public20200518@10.0.0`,早期只接最常用子集 |
| lancedb 升级不兼容 | 锁版本号,升级走单独 PR |
| secrets.dat 损坏 | 启动时若损坏,要求用户重新输入所有凭证并轮换 nonce |
| 前端组件库 API 大改(Base UI 还在 pre-1.0) | 锁版本,关键交互在自有 hooks 内封装 |
| 集成测试易脆 | 用 staging 而非生产;测试用专属子账号,断网/限流时跳过 |

## 14. 实施里程碑(高级概览,详细计划由 writing-plans 阶段产出)

> 本节只列高层 M0–M6,**不**是实现计划。详细任务拆分、估时、依赖关系在 writing-plans 阶段生成 `2026-07-20-dataworks-agent-plan.md`。

1. **M0 Fork 基线与治理**:导入固定 OpenCode SHA、upstream remote 约定、许可证、CI、dry-run health
2. **M1 Auth + DataWorks Workspace**:本地多用户登录、Workspace/Project 绑定、加密凭证、HttpApi/SDK
3. **M2 DataWorks 数据平面**:官方 OpenAPI adapter、PyODPS sidecar、MCP adapter、审计与写权限
4. **M3 DataWorks Agent 工具**:dw_* 插件工具、PermissionV1、Session/事件流真实闭环
5. **M4 Web 产品化**:在 OpenCode SolidJS app 增加 DataWorks 导航/页面,应用 new-api 风格 token
6. **M5 Skill + RAG**:复用 OpenCode Skill,扩展 DataWorks 权限元数据、知识库摄入、LanceDB 检索
7. **M6 真实验收与发布**:staging 集成、Playwright、Windows/Linux 打包、上游同步演练、release pipeline