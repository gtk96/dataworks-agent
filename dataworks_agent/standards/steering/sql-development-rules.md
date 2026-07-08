---
inclusion: fileMatch
fileMatchPattern: "**/*.sql"
description: SQL开发铁律：先查表结构再写代码，禁止编造字段
---

# SQL 开发铁律

## 代码风格

- SQL 关键字全小写：`select`/`insert`/`from`/`where`/`left join`/`union all`/`partition by`/`order by`/`qualify` 等
- 字段名全小写，下划线分隔
- 表别名用 t1/t2/t3...（数字递增），不用 r/o/s/l/f 等语义缩写
- DML SELECT 列当 ODS 字段名与 DWD 目标字段名不同时，必须加 `as 目标字段名`（如 `t1.conversation_id as session_id`）；即使名称相同，cast/函数转换后也加 `as`（如 `cast(t1.id as string) as msg_source_id`）——提高可读性，方便核对列对齐
- **day 表 JOIN hour 表时取整天数据**：day 表调度用 `${bizdate}`，关联 hour 表（dt+ht 分区）时 WHERE 条件只写 `dt='${bizdate}'`（取当天所有小时分区按主键去重取最新），不能写 `dt+ht` 只取某个小时——否则只拿到一个小时的数据
- **`left anti join` 直接接表名**，不套子查询；分区过滤和类型转换写在 ON 条件里（如 `on cast(t3.id as string) = t2.source_id and t3.dt = '${bizdate}'`）
- **ODS 导入语句禁止用 `select *`**：静态分区模式（`partition(dt='xxx')`）下 `select *` 包含分区字段会导致列数不匹配；必须显式列出所有非分区字段
- 不套多余子查询：`insert overwrite ... select ... union all select ...` 直接写，不用外层 `select * from (...) t` 包裹

## 核心原则：先查后写，禁止编造

### 1. 禁止编造字段（最高优先级）

在编写任何 DML/DDL 之前，**必须先查询来源表的真实字段结构**，严禁凭记忆或猜测编造字段名。

违规示例（过去犯过的错）：
- 来源表没有 `brand` 字段，却在 WHERE 中写了 `t1.brand = 'veimia'`
- 来源表没有 `product_id`，却直接引用（实际字段是 `sale_id`）
- 来源表没有 `media_status`，却写了 `t1.media_status = 'active'`
- 来源表没有 `ctr`/`cpc`/`cpm` 字段，却直接 SELECT（实际需要计算）
- 来源表没有 `site_name`，却直接引用（实际需要关联维度表）

### 2. 查表字段的标准流程

每次写 DML 前，必须执行以下步骤：

```sql
-- 步骤1：查询每张来源表的真实字段
select column_name, column_comment, data_type
from information_schema.columns
where table_schema = 'dataworks'
    and table_name = '来源表名'
order by ordinal_position
limit 200;
```

- 通过 BFF `createExecutorJobV3` 提交查询
- 通过 `getExecutorJobResult` 获取结果
- 或通过 MCP `submit_odps_sql` + `get_odps_sql_result` 查询
- **拿到真实字段列表后，才能开始写 DML**

### 3. 字段映射必须有据可查

DML 中的每个字段映射必须能在来源表字段列表中找到对应：
- 直接映射：`t1.sale_id as product_id`（sale_id 确实存在于来源表）
- 计算字段：`t2.spend_amt / t2.clicks as cpc`（spend_amt 和 clicks 确实存在）
- 关联字段：需要额外 JOIN 维度表时，必须先查维度表字段确认存在

### 4. 词根校验

生成 DDL 时，字段命名必须参考线上词根表：

```sql
-- 查询最新词根规范
select *
from dataworks.dim_pub_column_dictionary_static
limit 500;
```

- 字段名必须由词根表中已有的词根组合而成
- 禁止使用词根表中不存在的词根
- 如需新词根，需先确认后再使用

### 5. 检查清单（每次写 DML 前必须完成）

- [ ] 已查询所有来源表的 `information_schema.columns`
- [ ] 已确认 SELECT 中每个字段在来源表中真实存在
- [ ] 已确认 WHERE 条件中每个字段在来源表中真实存在
- [ ] 已确认 JOIN 键在两侧表中都存在
- [ ] 需要的字段如果来源表没有，已找到正确的维度表补充
- [ ] 需要计算的指标（如 ctr/cpc/cpm），已确认计算所需的基础字段存在

### 6. 写入 DataWorks 后的必做收尾（禁止跳过）

通过 BFF `updateNode` 将 DML/DDL 写入 DataWorks 节点后，**必须按顺序执行以下步骤**，不允许写完就结束：

1. **刷新确认**：`navigate_page type=reload` 或点击编辑器「刷新」按钮，确认内容已写入
2. **格式化代码**：按 `Shift+Alt+F` 格式化，然后 `Ctrl+S` 保存
3. **再次刷新确认**：确认格式化后的代码已保存
4. **如有弹窗**：如弹出"检测到文件未保存"对话框，点击"保存"

违规示例（过去犯过的错）：
- 通过 `updateNode` 写入 DML 后直接结束，没有格式化，导致代码风格不统一
- 格式化后忘记 `Ctrl+S` 保存，刷新后格式化丢失
