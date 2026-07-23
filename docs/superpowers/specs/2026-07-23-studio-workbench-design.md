# DataWorks Studio Workbench 设计规格

日期：2026-07-23

仓库：`E:\dataworks_agent`

基线：`master` @ `da5c199dcb72502e2e58a7deec772251b48fda5b`

目标分支：`studio-workbench`（书面规格批准后创建）

参考对象：MaxCompute Query Studio 1.2.4

## 1. 目标

把当前以 Chat Hero 和传统管理页面为主的 DataWorks UI，改造成接近 MaxCompute Query Studio 的专业数据工作台。

第一期聚焦两个表面：

1. 全局控制台外壳；
2. Chat / Agent 主工作区。

用户进入应用后，应在同一个工作台内完成以下闭环：

1. 选择连接和项目；
2. 浏览表与 Schema；
3. 与 Agent 讨论并生成 Plan 或 SQL；
4. 在中央工作区检查、编辑 SQL；
5. 明确点击 Run 执行只读查询；
6. 查看结构化结果，并把有限的结果预览作为后续 Agent 上下文。

## 2. 非目标

第一期明确不做：

- 重写 OpenCode Session、消息时间线、权限或模型运行机制；
- 新增 MaxCompute/DataWorks 后端接口；
- 允许 Agent 自动执行 SQL；
- 把写操作混入只读 SQL 编辑器；
- 在浏览器持久化凭据、SQL 结果、Agent 消息或 SQL 正文；
- 重做 connections、jobs、skills、knowledge、audit 等管理页面的业务逻辑；
- 为追求视觉一致性而大范围重构无关模块；
- 复制 Query Studio 的品牌、文案或受保护资源。

## 3. 当前代码基线

第一期应组合现有能力，而不是重新发明数据访问和会话层。

当前检出只存在并跟踪 `master` / `origin/master`，没有本地或远端 `dev` 引用；因此本规格记录实际检出提交。创建目标分支前仍需重新检查引用，若届时出现 `dev`，按仓库约定以 `dev` 或 `origin/dev` 作为比较基线。

### 3.1 可复用能力

- `packages/app/src/context/dataworks.tsx`
  - 已有连接、项目和选中状态；
  - 已有 `listProjects`、`listTables`、`describeTable`、`runSql`；
  - 已有 `ListState` 和只读/写入控制面接口；
  - 请求使用同源 Cookie，不把 Token 写入 `localStorage`。
- `packages/app/src/pages/dataworks/explorer.tsx`
  - 已有项目、表、Schema、SQL 编辑和结果获取逻辑；
  - 当前问题是这些能力堆叠在一个传统页面内，缺少工作台信息架构。
- `packages/app/src/components/dataworks/console-layout.tsx`
  - 已有受保护路由、控制台导航、顶部栏和登录跳转；
  - 可升级为新的工作台外壳。
- `packages/app/src/pages/dataworks/dashboard.tsx`
  - 已有 Chat 草稿创建、运行时检查、连接/项目作用域提示；
  - 当前 Chat Hero 将被右侧 Agent 面板取代，不保留重复的中央聊天入口。
- 现有 Session 页面、消息时间线、Composer、权限审批和 Todo/Plan 表面继续复用。

### 3.2 已知基线问题

`packages/app` 当前类型检查在 `dashboard.tsx` 读取 `ServerConnection.Any.name` 时失败。工作台改造会触及该代码，必须消除这个错误，并在最终报告中区分基线问题与本次回归。

## 4. 设计方向

采用已确认的“Studio Cockpit + Dual-channel Dark”方向：

- 信息架构紧跟 Query Studio：窄导航轨、资源树、中央制品工作区、常驻 Agent 面板；
- 视觉不是泛化黑色后台，而是高密度、低装饰、可长期使用的数据工具；
- 青色只表示读取、上下文、选中和焦点；
- 琥珀色只表示运行、写入和高风险动作；
- 真实错误使用珊瑚红，空状态和普通提示不使用错误色；
- 中央区域承载 Plan、SQL、Results、Schema，右侧只承载对话，避免内容重复。

## 5. 工作台布局

### 5.1 桌面结构

从左到右分为四栏：

1. **Global Rail**：全局功能入口；
2. **Resource Explorer**：连接、项目、表和对象树；
3. **Artifact Workspace**：Plan、SQL、Results、Schema；
4. **Agent Panel**：当前 Session 对话和审批交互。

顶部为作用域、标题和主要动作工具栏；底部为连接、项目、运行状态和结果截断状态栏。

默认尺寸：

| 区域 | 默认值 | 约束 |
|---|---:|---|
| Global Rail | 46px | 固定宽度 |
| Resource Explorer | 240px | 可调整，200–360px |
| Artifact Workspace | 剩余空间 | 最小 480px，始终优先保留 |
| Agent Panel | 视口约 30% | 可调整，320–600px，可折叠 |
| Top Toolbar | 40px | 固定高度 |
| Status Bar | 24px | 固定高度 |

面板拖拽只改变相邻栏宽；折叠后保留明确的恢复按钮，不依赖悬停发现。

### 5.2 全局导航

导航轨延续现有路由能力，但只显示图标和短 Tooltip：

- Agent / Studio；
- Connections；
- Explorer；
- Jobs；
- MCP；
- Skills；
- Knowledge；
- Audit；
- Settings。

第一期只为 Agent / Studio 使用完整四栏工作台。其他管理路由继续使用统一深色外壳和顶部栏，不强行塞入资源树与 Agent 面板。

### 5.3 资源树

资源树按以下层级显示：

```text
Connection
└─ Project
   ├─ Tables
   │  └─ Table
   ├─ Functions
   └─ Recent
```

第一期真实接入 Connection、Project、Tables 和 Table Schema。Functions 没有可靠数据源时不显示伪节点；Recent 仅在已有真实本地会话数据可复用时出现。

点击项目更新共享作用域；点击表选中该表并打开 Schema。双击表名可把安全的 `SELECT * FROM <table> LIMIT 100` 模板放入 SQL，但仍不执行。

## 6. 中央制品工作区

中央区域包含四个固定一级标签。标签不被 Agent 消息替代，也不复制聊天内容。

### 6.1 Plan

- 显示当前 Session 已存在的计划、Todo 或步骤状态；
- Agent 输出可通过“在 Plan 中打开”进入此标签；
- 没有计划时显示轻量空状态，不生成虚假步骤；
- Plan 是只读投影，编辑计划仍通过 Agent 对话完成。

### 6.2 SQL

- 提供可编辑 SQL 文本区和 SQL 文档子标签；
- Agent 消息中的明确 SQL 代码块提供“在 SQL 中打开”动作；
- 如果当前 SQL 文档未修改，动作更新当前文档；如果已有未运行修改，则新建内存文档，不能静默覆盖；
- Agent 写入编辑器后绝不自动调用 `runSql`；
- Run 是琥珀色主动作，只在连接、项目、项目名和 SQL 都有效时可用；
- 运行继续使用现有只读 SQL 接口和服务端只读校验；UI 可以提前提示明显写语句，但不能把前端判断当作安全边界；
- 写操作继续使用独立 Agent 权限、票据与审计链路。

SQL 文本只保存在当前页面内存和既有 Session 制品中，不新增浏览器持久化。

### 6.3 Results

- 成功运行后自动激活 Results；
- 用真实列头和表格展示结果，不再输出 JSON 文本块；
- 显示行数、耗时、实例 ID 和 `truncated` 状态；
- 后端请求仍限制 `maxRows = 1000`、`timeoutMs = 30000`；
- 大结果使用虚拟滚动或等价的受控渲染，不能一次生成无限 DOM；
- SQL 编辑后，旧结果保留但标记“基于旧版本 SQL”；再次运行后替换；
- 切换连接或项目时清空结果，避免跨作用域误读；
- 结果不写入 `localStorage`、`sessionStorage` 或 IndexedDB。

### 6.4 Schema

- 点击资源树表节点时自动激活或更新 Schema；
- 使用现有 `describeTable` 返回的列名、类型、注释、分区和主键信息；
- 描述接口失败时保留表选择，显示可重试错误；
- 若列表行包含基础 Schema 信息，可作为降级摘要，但必须标记为不完整，不能伪装成完整列定义。

## 7. Agent 面板

### 7.1 职责

Agent 面板复用现有 Session 和 Composer，负责：

- 自然语言对话；
- 当前计划与执行过程；
- 权限问题和写操作审批；
- 把 Agent 生成的 Plan 或 SQL送入中央工作区；
- 接收用户主动附加的当前表 Schema 或有限结果预览。

Agent 面板不负责：

- 直接执行中央 SQL；
- 展示完整结果表；
- 维护第二份连接/项目选择器；
- 在没有用户动作时吞入无限结果行。

### 7.2 Agent 与中央区契约

工作台内部定义小型、带类型的制品桥接契约：

- Plan 制品：标题、步骤和来源消息 ID；
- SQL 制品：SQL 正文、建议标题和来源消息 ID；
- Schema 上下文：表身份和受限列定义；
- Result Preview：列元数据、前 20 行、最多前 50 列、耗时和截断状态。

桥接只发生在用户点击“在工作区打开”或“附加到对话”时。成功 SQL 运行不会自动向正在执行的模型回合追加内容；预览成为一个可见 Context Chip，用户发送下一条消息时才进入上下文。

## 8. 共享作用域

连接、项目和区域必须只有一个事实来源：现有 `DataWorksContext`。

共享作用域字段：

- `connectionID`；
- `projectID`；
- `projectName`；
- `region`。

资源树、中央工作区、状态栏和 Agent Context Chip 都从该作用域派生，不各自维护副本。

作用域切换规则：

- 切换连接后重新加载项目，并验证先前项目是否仍有效；
- 切换项目后重新加载表；
- 保留未运行 SQL 文本，但清空 Results 和当前 Schema；
- Agent 面板立即显示新作用域，下一条用户消息使用新作用域；
- 当前运行请求按启动时的不可变作用域完成，若完成时作用域已改变，结果不得进入新作用域面板，应标记为过期或丢弃。

## 9. 本地状态与安全

允许持久化：

- 资源树宽度；
- Agent 面板宽度和折叠状态；
- 当前一级工作区标签，以及可从既有 Session 重新读取的制品标签 ID 和标题；
- 最近有效的 `connectionID` 和 `projectID`。

禁止持久化：

- AccessKey、Secret、Cookie、Token；
- SQL 正文；
- 查询结果和 Result Preview；
- Agent 消息和权限票据；
- 完整 Schema 响应。

恢复时必须先用服务端返回的连接和项目列表验证已存 ID。失效 ID 被清除并回退到第一个有效项，不能让旧作用域停留在界面上。

## 10. 视觉系统

### 10.1 色彩

| Token | 值 | 用途 |
|---|---|---|
| Background | `#0C1118` | 中央工作区背景 |
| Panel | `#101720` | 资源树和 Agent 面板 |
| Elevated | `#151E29` | 浮层、选中行、卡片 |
| Divider | `#263445` | 分隔线和边框 |
| Primary Text | `#EDF6FB` | 主文字 |
| Muted Text | `#8DA1B2` | 辅助信息 |
| Context Cyan | `#5FC9D5` | 读取、上下文、选中、焦点 |
| Action Amber | `#E8AD46` | Run、写入、高风险动作 |
| Error Coral | `#F07878` | 仅真实失败 |

禁止用青色装饰所有可点击元素，也禁止用琥珀色表达普通选中状态。颜色必须保留语义稀缺性。

### 10.2 字体与密度

- UI：Inter 或现有系统无衬线栈；
- SQL、ID、数值：现有等宽 Token，优先 JetBrains Mono / Cascadia Code；
- 正文 12px，辅助信息 11px，重要标签 12–13px；
- 工具栏 36–40px；
- 一级标签 34px；
- 树行 28px；
- 常规交互目标最小 28px，关键按钮最小 32px。

### 10.3 形状和动效

- 控件圆角 4–6px，浮层 8px；
- 不使用大面积胶囊、渐变光晕和营销式阴影；
- 动效仅用于折叠、切换和加载反馈，持续时间 120–180ms；
- 尊重 `prefers-reduced-motion`。

## 11. 响应式与可访问性

### 11.1 响应式

- `>= 1280px`：四栏同时显示，Agent 默认约 30%；
- `960–1279px`：资源树可折叠，Agent 保持可见但允许缩至 320px；
- `< 960px`：Agent 自动收起，通过明确按钮以覆盖层恢复，中央编辑器优先；
- 极窄宽度下导航轨保留，资源树和 Agent 均使用覆盖层，不把编辑器压到不可用宽度。

### 11.2 键盘与焦点

- 标签、树节点、折叠按钮、Run 和 Agent 动作均可用键盘访问；
- 焦点环使用 2px Context Cyan，并有足够对比度；
- 面板拖拽器提供键盘调整和 `aria-valuenow`；
- 折叠按钮提供明确的 `aria-expanded`；
- Results 表头、行和错误状态提供语义结构；
- 状态变化通过合适的 `role=status` 或 `aria-live` 通知，不重复朗读流式内容。

## 12. 加载、空状态和错误

| 场景 | 表现 | 恢复动作 |
|---|---|---|
| 初始化连接 | 资源树局部骨架 | 自动完成 |
| 无连接 | 资源树和工作区引导卡 | 打开 Connections |
| 无项目 | 项目节点空状态 | 刷新项目 |
| 无表 | Tables 空状态 | 清除筛选或刷新 |
| Schema 加载 | Schema 局部骨架 | 自动完成 |
| SQL 运行 | Run 锁定并显示耗时 | 等待完成，不重复提交 |
| SQL 失败 | Results 内错误，不清空 SQL | 修改后重试 |
| HTTP 429 | 显示重试等待信息 | 到期后重试 |
| 部分数据 | 显示警告和已有内容 | 重试缺失部分 |
| 作用域已切换 | 丢弃或标记旧请求结果 | 在新作用域重新运行 |
| 未登录 | 保留 `returnTo` 跳转登录 | 登录后返回 |

错误信息应说明问题、影响和下一步，不向普通用户暴露堆栈。错误不能让导航轨和其他独立面板白屏。

## 13. 组件边界

命名在实现计划中可按现有目录习惯微调，但职责必须保持：

- `DataWorksConsoleLayout`
  - 受保护路由、全局导航和工作台外壳；
  - 不直接获取表、Schema 或 SQL 结果。
- `StudioWorkbench`
  - 组合四栏和顶部/底部状态；
  - 管理面板尺寸、折叠和当前一级标签。
- `ResourceExplorer`
  - 渲染连接、项目和表；
  - 调用 `DataWorksContext` 的列表与描述能力。
- `ArtifactWorkspace`
  - 管理 Plan、SQL、Results、Schema 标签；
  - 不维护第二份作用域。
- `SqlWorkspace`
  - SQL 文档、编辑状态、显式运行和旧结果标记。
- `ResultsGrid`
  - 结构化、受限地渲染 `DataWorksSqlResult`。
- `SchemaPanel`
  - 表描述加载和降级摘要。
- `AgentPanel`
  - 复用 Session、Timeline、Composer 和权限表面。
- `WorkbenchArtifactBridge`
  - 在 Agent 与中央区之间传递已确认的 Plan、SQL 和上下文制品；
  - 不发网络请求，不执行 SQL。

不应提前抽取只使用一次的微型 helper；只在上述真实边界或现有复用点拆分组件。

## 14. 测试策略

测试从包目录运行，禁止从仓库根目录运行测试，也不直接调用 `tsc`。

### 14.1 单元测试

- 面板宽度约束、折叠和断点规则；
- 持久化白名单和失效作用域恢复；
- SQL 文档覆盖保护；
- SQL 修改后的结果过期状态；
- 作用域切换时清除 Results/Schema；
- 旧作用域异步结果不能污染新作用域；
- Result Preview 的 20 行、50 列限制；
- Agent SQL 打开动作不调用 `runSql`。

### 14.2 组件和集成测试

- 资源树、中央区和 Agent 显示同一作用域；
- 点击表后 Schema 加载并切换标签；
- Agent SQL 进入编辑器但没有网络执行；
- 用户点击 Run 后只调用一次现有 SQL 接口；
- 成功后自动进入 Results 并显示列、行、耗时和截断状态；
- 错误、429、空状态和部分数据均可恢复；
- 折叠、恢复和键盘调整面板可操作；
- 认证跳转和 `returnTo` 不回归。

测试优先覆盖真实组件和状态逻辑。网络边界使用受控的本地测试服务器或现有测试夹具，不修改 `globalThis`，不连接真实写入环境。

### 14.3 浏览器验收

在本地应用验证：

- 1440px 四栏布局；
- 1024px 资源树折叠；
- 768px Agent 自动收起和恢复；
- 连接/项目切换；
- 表浏览和 Schema；
- Agent 到 SQL；
- 手工运行 `SELECT 1` 或等价只读查询；
- Results 表格、过期状态和预览 Context Chip；
- 键盘焦点、折叠和 Run；
- 控制台无新增错误。

默认使用测试数据、受控夹具和只读探针。任何真实写操作都不属于本规格的验收范围。

### 14.4 必须通过的包级门槛

从 `packages/app` 运行：

- 与工作台相关的 Bun 测试；
- `bun typecheck`；
- 适用的格式化/静态检查；
- 本地构建或开发服务器烟测。

最终门槛包括消除当前 `dashboard.tsx` 的类型错误，且不能以跳过文件或降低类型约束的方式通过。

## 15. 验收标准

以下条件全部满足才可认为第一期完成：

1. 页面信息架构清晰接近 Query Studio，且没有复制品牌资源；
2. Agent 面板常驻桌面右侧，默认约 30%，可调整、折叠和恢复；
3. 中央 Plan、SQL、Results、Schema 四个标签均连接真实现有能力或真实 Session 状态；
4. 不再存在重复的中央 Chat Hero；
5. Agent 生成 SQL 只能打开或更新 SQL，绝不自动运行；
6. Run 只走现有只读 SQL 路径，写操作仍走票据、权限和审计；
7. 资源树、中央区、状态栏和 Agent 的连接/项目/区域始终一致；
8. SQL 成功后自动打开结构化 Results，而不是 JSON 文本；
9. Agent 最多获得 20 行、50 列的显式附加预览；
10. 浏览器只持久化安全的 UI 状态和作用域 ID；
11. 三个目标宽度的响应式行为符合本规格；
12. 关键操作可用键盘完成并具有清晰焦点；
13. 包级测试、类型检查和浏览器烟测达到约定门槛；
14. 当前 Dashboard 类型错误被消除，没有新增控制台错误或敏感数据泄漏。

## 16. 风险与约束

| 风险 | 缓解方式 |
|---|---|
| Session UI 与 DataWorks 壳层职责交错 | 复用 Session 内核，只增加窄的 Agent 容器与制品桥接 |
| Agent 输出格式不稳定 | 只对明确的 Plan/SQL 制品或标记代码块提供打开动作，不猜测普通文本 |
| 异步请求跨作用域串数据 | 请求捕获启动作用域，完成时再次比对 |
| 大结果卡顿或泄漏 | 后端行数限制、受控渲染、内存态、有限预览 |
| 深色主题污染其他 OpenCode 页面 | Token 和布局限定在 DataWorks 工作台边界内 |
| 一次改动范围过大 | 第一期只改壳层和 Agent 工作区，管理页仅保持可达和视觉兼容 |
| 既有类型错误干扰验收 | 在开始和结束分别记录门槛，触及代码时直接修复根因 |

## 17. 后续流程

本规格提交并由用户书面审阅通过后：

1. 使用 `writing-plans` 编写详细实现计划；
2. 使用隔离 worktree 创建 `studio-workbench` 分支；
3. 按测试驱动方式逐步实现；
4. 在 `packages/app` 内执行包级验证；
5. 完成后进行代码审查和浏览器验收。
