# DataWorks 对话入口 · X 风格（ChatGPT 式极简）

日期：2026-07-23  
仓库：`E:\dataworks_agent`  
分支：`chat-first-ui`（基于 `42ecc271d`）  
状态：待用户审阅

---

## 1. 目标

把 `DataWorksDashboard` 从"控制台缩略图"改成 **ChatGPT 式对话入口**：首屏 90% 留白，唯一主角是大输入框，4 条灰色提示词，**没有任何彩色装饰**。

参考：https://chatgpt.com（首屏交互、留白、字体、提示词样式）

---

## 2. 非目标（明确不做）

- ❌ KPI 卡片（4 张渐变色卡）—— 整块删
- ❌ 快捷操作彩色卡（4 张带 icon 的卡片）—— 改成 placeholder 灰色提示
- ❌ 顶部 context bar（连接 / 项目 / env 字段横排）—— 删
- ❌ 底部 status strip（连接 / 写权限 / 模型 / 时间）—— 删
- ❌ 独立"开始查询"标题面板（"开始查询 · …"）—— 删
- ❌ 独立"常用操作"标题面板 —— 删
- ❌ 渐变 mesh 背景、彩虹装饰条、彩色图标块 —— 删
- ❌ 当前对话页里再选一遍项目 —— 沿用控制台 context，不允许切换

**保留**：侧栏（折叠产品入口到"工具"下拉）、大输入框、发送按钮、4 条灰色提示词

---

## 3. 视觉规范

### 3.1 颜色（只允许以下 token，所有新代码必须使用，不允许任何硬编码 hex）

| 角色 | token | light | dark | 用途 |
|---|---|---|---|---|
| 主文字 | `--dwa-text` | `#0d0f12` | `#e8eaed` | 标题、正文 |
| 次要文字 | `--dwa-text-secondary` | `#5b6068` | `#a0a6b0` | 描述 |
| 辅助文字 | `--dwa-text-tertiary` | `#9097a1` | `#6b7280` | placeholder、meta |
| 边框 | `--dwa-border` | `rgba(13,15,18,0.08)` | `rgba(255,255,255,0.08)` | 输入框、卡片 |
| 表面 | `--dwa-surface` | `#ffffff` | `#1a1f26` | textarea |
| 页面底色 | `--dwa-page` | `#fafafa` | `#0f1419` | 主区 |
| Primary | `--dwa-primary` | `#1f6feb` | `#60a5fa` | 发送按钮、focus 环 |
| Primary 软 | `--dwa-primary-soft` | `rgba(31,111,235,0.08)` | `rgba(96,165,250,0.12)` | 链接 hover |
| 错误 | `--dwa-danger` | `#dc2626` | `#f87171` | 仅错误态 |
| 警告 | `--dwa-warning` | `#d97706` | `#fbbf24` | 仅状态点 |

**纪律**：上表之外的颜色不允许出现。删除 dashboard.css 里全部 `#f5f3ff`、`#fecaca`、`#86efac`、`#fdba74`、`#93c5fd`、`#c4b5fd`、`#67e8f9` 等色值。

### 3.2 字体

| 角色 | size / weight | line-height | tracking | 字体 |
|---|---|---|---|---|
| 输入框正文 | 15.5px / 450 | 1.55 | 0 | Inter / 系统无衬线 |
| placeholder | 15.5px / 400 | 1.55 | 0 | 同上 |
| 提示词 | 13.5px / 450 | 1.4 | 0 | Inter |
| 焦点环标签 | 11.5px / 600 | 1 | 0.02em | ui-monospace |

`var(--font-family-text, "Inter", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif)` 已存在于 theme，沿用。

### 3.3 圆角

| 元素 | 值 |
|---|---|
| textarea | 16 |
| 提示词 chip 行 | 无边框、无圆角（仅文字 + 下划线 hover） |
| 发送按钮 | 12 |
| 侧栏 / 抽屉 | 0 |

**禁止 14、18 等孤值**。

### 3.4 阴影

- `--shadow-focus`: `0 0 0 4px rgba(31,111,235,0.12)` — **textarea 唯一焦点效果**
- 其它状态不叠阴影

### 3.5 间距

4px base：`4 / 8 / 12 / 16 / 24 / 32 / 48`

主区 layout：
- 主区背景 `#fafafa`，整页 `padding: 0`
- 内容容器 `width: min(720px, 100%)`、`margin: 0 auto`
- 容器顶部 `padding-top: clamp(80px, 18vh, 160px)`（**首屏标题居于视口偏上**）
- 容器内部间距 `gap: 32`

### 3.6 背景

- 主区底色 `--dwa-page`（`#fafafa`）
- **不要** mesh gradient、radial ambient、点阵纹理
- 侧栏维持深色（`#1b2332 → #151c28` 线性渐变已存在于 `console-layout.css`），不变

---

## 4. 信息架构

### 4.1 主区（首屏）

```
[data-component="dataworks-dashboard"] / .dwa-page-stack
├─ .dwa-chat-hero        (容器，clamp padding-top)
│   ├─ .dwa-chat-greeting  (可选 <h1>，单行 26px / 650，letter-spacing -0.02em)
│   │   文案：language.t("dataworks.chat.hero") — "今天想查点什么？"
│   ├─ .dwa-chat-composer  (textarea 容器，focus 唯一加光晕)
│   │   ├─ <textarea>
│   │   └─ .dwa-chat-send  (右上角 ↑ 按钮，hover 显深色，静止 12% 透明)
│   └─ .dwa-chat-hints     (灰色 4 行提示词，每行 ≤ 50 字符)
```

**textarea 内部不放任何元素**（不放 chip、不放快捷按钮、不放状态点）。点击提示词 → 自动填入 textarea 并聚焦，**不自动发送**。

### 4.2 侧栏改动

- 主导航保留 1 个：`对话`（当前激活）
- 其余 5 个产品入口（连接 / 探索 / 任务 / MCP / 审计）**折叠成侧栏底部"工具 ▾"下拉**
- 新对话按钮保留为侧栏顶部 + 按钮
- 历史会话分组保留：今天 / 昨天 / 7 天

**侧栏的修改属于本次范围**（之前没做下拉折叠，这次补上）。

### 4.3 删除的元素清单

| 文件 | 删除 |
|---|---|
| `dashboard.tsx` | `StatusCard` 组件、`<section class="dwa-status-grid">`、`<section class="dwa-quick-grid">`、`<section class="dwa-composer">`、`<dwa-callout>` for 缺项目、`<dwa-callout>` for 缺连接、`<dwa-page-head>`、`<dwa-toolbar>`、`runtimeReady` memo（同步删除 `runtime` reason）、`sending()` state 中的发送按钮 disabled 逻辑 |
| `dashboard-utils.ts` | `queryDashboardState` 改为仅检查 `prompt.trim().length > 0` 与 `selectedConnection/project` 是否存在（**运行时从 dashboard 删除，这里只留空 prompt 检查 + 错误文案映射**）。`quickActionLabel`、`quickActionHint` 改为 4 个 hint 文案。`DashboardReadiness.reason` 改为只 `prompt / ok` |
| `dashboard.css` | 删除 `.dwa-status-grid` / `.dwa-status-card*` / `.dwa-quick-grid` / `.dwa-quick-card*` / `.dwa-callout*` / `.dwa-composer*` / `.dwa-page-head` / `.dwa-toolbar` / `.dwa-btn-primary` / `.dwa-btn-secondary` / `.dwa-btn-ghost` / `.dwa-btn-sm` / `.dwa-btn-lg` 中只在 dashboard 用的样式 / 渐变背景 / 彩虹条 |
| i18n | 删除 `dataworks.dashboard.currentConnection / currentProject / todayQueries / writePermission / start / startHint / needProjectTitle / projectEmpty / projectLoadError / quick / quickHint`。新增 `dataworks.chat.send`、`dataworks.chat.hint.<key>` |

---

## 5. 组件结构（拆分后）

```
packages/app/src/pages/dataworks/
├─ dashboard.tsx              容器：状态、发送、错误提示（仅保留 prompt signal + sending）
├─ dashboard-utils.ts         prompt 校验 + 4 条 hint 文案 + 错误映射
├─ dashboard-chat-hero.tsx    textarea + ↑ 发送按钮 + focus 状态
├─ dashboard-chat-hints.tsx   4 行灰色提示词（点填入）
├─ dashboard-chat-error.tsx   出错时 inline 显示在 textarea 下方（默认 0 高度）
├─ dashboard.css              重写为极简（hero + textarea + hints + error）
└─ dashboard.test.ts          保留（dashboard-utils 纯函数测试不动）
```

容器持 signal，子组件接 accessor。

---

## 6. 交互规范

### 6.1 键盘

| 快捷键 | 行为 |
|---|---|
| `⌘/Ctrl + L` | 聚焦 textarea（自动 focus） |
| `⌘/Ctrl + Enter` | 发送 |
| `Enter` | 换行 |
| `Esc` | 失焦 |

页面 mount 时**自动 focus textarea**（微任务里执行，避免动画抢焦点）。

### 6.2 发送流程

1. 用户输入文本（或点提示词填入）
2. 点 ↑ 或按 `⌘/Ctrl+Enter`
3. 状态：`sending = true`，按钮 disabled + 文案切换 "发送 → 发送中"
4. `tabs.newDraft(...)` 调用，**不再 navigate**（之前已修）
5. 失败：toast 提示 + 文本回填到 textarea
6. 成功：路由 `/new-session?draftId=…` 跳转，主区淡出 80ms

### 6.3 错误处理

- **未配连接**：textarea 上方一行 inline 提示 + 链接"添加连接"
- **项目不可用**：textarea 上方一行 inline 提示 + 链接"刷新"  
- **OpenCode 离线**：发送时 toast，按钮恢复
- **模型不可用**：发送时 toast，文本回填
- **空 prompt**：按钮 disabled（这是**唯一允许长期 disabled 的场景**）+ focus textarea

### 6.4 提示词交互

- 4 行文本，每行 ≤ 50 字符
- 默认灰色 `--dwa-text-tertiary`
- hover：颜色变 `--dwa-text-secondary`、底部出 1px 下划线
- click：填入 textarea 并**全选**，焦点落到 textarea，**不发送**
- 文案来源：`dataworks.chat.hint.tables / jobs / orders / ping`（沿用 i18n key，替换之前的 `quickAction*`）

### 6.5 加载与发送态

| 状态 | 视觉 |
|---|---|
| 正常 | textarea 白底、border `rgba(13,15,18,0.08)`、无光晕 |
| focus | border `--dwa-primary` + 4px halo `rgba(31,111,235,0.12)` |
| 发送中 | textarea opacity .85、readonly、按钮 disabled + 文案切换 |
| 错误 | textarea 下方 1 行 12px 红色文字 + 操作链接 |

---

## 7. 动效

```
--motion-fast: 120ms
--motion-base: 180ms
--motion-ease: cubic-bezier(.2,.8,.2,1)
```

- 进入页面：**textarea 120ms 上移 4px + opacity 0→1**，提示词 60ms 后再 120ms 上移 + opacity
- focus：120ms ease，边色 + halo
- 发送中：180ms ease，opacity .85
- 错误条：120ms ease，高度 + opacity 同步
- `prefers-reduced-motion: reduce` → 所有 transition 折到 0.01ms

**禁止**：shake、bounce、pulse、彩虹装饰条、loading 旋转图标。

---

## 8. 工程约束

- **不引入新依赖**（SolidJS + 自写 CSS 已足够）
- **不修改** `dashboard-utils.ts` 中纯函数测试的导入路径
- **不删除**任何现有测试文件
- **不修改** `dataworks-theme.css` 已定义的 `--dwa-*` token，只补完缺失 token
- **不修改**侧栏代码本身，只在 `dashboard.tsx` 范围内重写
- dark mode 全部通过 `var(--dwa-*)` token 实现，**禁止 `!important`**

---

## 9. 文件改动清单

| 文件 | 改动 |
|---|---|
| `pages/dataworks/dashboard.tsx` | 重写为容器，删除 KPI/快捷卡/context bar/status strip |
| `pages/dataworks/dashboard-utils.ts` | 精简到 `prompt 校验 + 4 条 hint 文案` |
| `pages/dataworks/dashboard-chat-hero.tsx` | 新建：textarea + ↑ 按钮 |
| `pages/dataworks/dashboard-chat-hints.tsx` | 新建：4 行灰色提示 |
| `pages/dataworks/dashboard-chat-error.tsx` | 新建：inline 错误条 |
| `pages/dataworks/dashboard.css` | 重写为极简 |
| `pages/dataworks/dashboard.test.ts` | **不修改**（dashboard-utils 测试仍能跑） |
| `i18n/zh.ts` / `i18n/en.ts` | 删除 7 个 key，新增 `dataworks.chat.send` + 4 个 `dataworks.chat.hint.*` |
| `styles/dataworks-theme.css` | 补 `--dwa-text-secondary` / `--dwa-text-tertiary` / `--shadow-focus` 等 token |

---

## 10. 验收

1. 浏览器 hard refresh 后访问 `/`（已登录 admin/admin）
2. 主区看到：**大 textarea 占视觉中心**、**顶部 1 行灰色 greeting**、**底部 4 行灰色提示词**、**右上角 ↑ 按钮**
3. **没有任何 KPI 卡、彩色 chip、装饰条、context bar、status strip**
4. textarea mount 时自动 focus（光标可见）
5. 点提示词任一行 → 文本填入 textarea，**未发送**
6. 输入文字 + 点 ↑ → 进入 `/new-session?draftId=…`，主区淡出
7. 切到深色模式：底色变 `#0f1419`，textarea 变 `#1a1f26`，主文字 `#e8eaed`，focus 环变蓝
8. `prefers-reduced-motion: reduce` 模拟下：所有过渡瞬间完成
9. `dashboard.test.ts` 仍 pass（≥8 cases，0 fail）
10. 浏览器 console 0 error / 0 warning