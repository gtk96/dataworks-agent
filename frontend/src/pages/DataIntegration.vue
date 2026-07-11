<template>
  <div>
    <el-radio-group v-model="odsPath" style="margin-bottom:20px" @change="onPathChange">
      <el-radio-button value="holo">
        <el-icon style="vertical-align:middle;margin-right:4px"><DataBoard /></el-icon>ODS Holo
      </el-radio-button>
      <el-radio-button value="di">
        <el-icon style="vertical-align:middle;margin-right:4px"><Connection /></el-icon>ODS DI
      </el-radio-button>
      <el-radio-button value="mc">
        <el-icon style="vertical-align:middle;margin-right:4px"><Coin /></el-icon>ODS MC
      </el-radio-button>
      <el-radio-button value="oss">
        <el-icon style="vertical-align:middle;margin-right:4px"><Upload /></el-icon>OSS 导入
      </el-radio-button>
      <el-radio-button value="realtime">
        <el-icon style="vertical-align:middle;margin-right:4px"><Timer /></el-icon>实时 ODS
      </el-radio-button>
      <el-radio-button value="batch">
        <el-icon style="vertical-align:middle;margin-right:4px"><Upload /></el-icon>批量部署
      </el-radio-button>
    </el-radio-group>

    <!-- ========== ODS Holo ========== -->
    <template v-if="odsPath === 'holo'">
      <el-steps :active="step" align-center style="margin-bottom:24px">
        <el-step title="选表" description="Holo 读端 + 字段" />
        <el-step title="Holo SQL" description="预览 DML / 创建节点" />
      </el-steps>

      <el-card v-if="step === 0">
        <el-alert type="info" :closable="false" style="margin-bottom:16px">
          <template #title>ODS Holo：{{ holoReadRef || '选 schema + 表' }} → cda.{{ targetTable || 'ods_hl_*' }}</template>
          <div style="font-size:13px;line-height:1.6;color:#606266">
            读端为 Holo 内 <code>{schema}.{表}</code>；列表与字段均来自元数据查询，无需再手工确认同步状态。
          </div>
        </el-alert>
        <el-row :gutter="16">
          <el-col :span="6">
            <el-form-item label="Holo 原生 schema">
              <el-select
                v-model="holoSchema"
                placeholder="ofc / oms / …"
                filterable
                allow-create
                default-first-option
                @change="loadHoloTables"
                style="width:100%"
              >
                <el-option v-for="s in holoSchemas" :key="s" :label="s" :value="s" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="10">
            <el-form-item :label="holoTablesLoading ? '加载中...' : holoSchema ? `Holo 源表 (${holoTables.length})` : '选 schema 后加载'">
              <el-select
                v-if="holoSchema"
                v-model="selectedTable"
                placeholder="s_order / t_platform_order …"
                filterable
                allow-create
                default-first-option
                style="width:100%"
              >
                <el-option v-for="t in holoTables" :key="t.name" :label="t.name" :value="t.name" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="Holo 读端">
              <el-input :model-value="holoReadRef" readonly placeholder="ofc.s_order" />
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="粒度">
              <el-select v-model="granularity" style="width:100%">
                <el-option value="hour" label="小时" />
                <el-option value="day" label="天" />
                <el-option value="min" label="分钟" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-alert
          v-if="holoTableSource === 'hologres'"
          type="success"
          :closable="false"
          :title="`已在 Holo 实例 ${HOLO_INSTANCE} 中发现 ${holoReadRef}`"
          style="margin-bottom:12px"
        />
        <el-alert
          v-else-if="holoTableSource === 'mysql_reader_hint'"
          type="warning"
          :closable="false"
          title="表名来自 MySQL Reader 辅助列表；若 Holo 内无此表，字段/DML 可能失败"
          style="margin-bottom:12px"
        />
        <div style="margin-bottom:12px">
          <span style="font-size:12px;color:#999;margin-right:8px">常用 schema：</span>
          <el-button v-for="n in ['ofc', 'oms', 'gimp']" :key="n" size="small" @click="pickHoloSchema(n)">{{ n }}</el-button>
        </div>
        <div v-if="selectedTable && holoSchema" style="margin-bottom:16px">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
            <span style="font-size:13px;color:#606266">表结构预览</span>
            <el-button size="small" @click="loadHoloColumns" :loading="holoColumnsLoading">刷新</el-button>
            <el-tag v-if="holoColumnMeta.metadata_source" size="small" type="info">
              来源: {{ METADATA_SOURCE_LABEL[holoColumnMeta.metadata_source] || holoColumnMeta.metadata_source }}
            </el-tag>
            <el-tag v-if="holoColumnMeta.split_pk" size="small">PK: {{ holoColumnMeta.split_pk }}</el-tag>
            <el-select
              v-if="holoWhereOptions.length"
              v-model="holoWhereMode"
              size="small"
              style="width:min(420px, 100%)"
              placeholder="增量 WHERE"
              @change="onHoloWhereModeChange"
            >
              <el-option
                v-for="opt in holoWhereOptions"
                :key="opt.mode"
                :label="opt.label"
                :value="opt.mode"
              />
            </el-select>
          </div>
          <el-alert
            v-if="holoColumnsError"
            type="error"
            :closable="false"
            :title="holoColumnsError"
            style="margin-bottom:8px"
          />
          <el-table
            v-else-if="holoColumns.length"
            :data="holoColumns"
            size="small"
            border
            max-height="280"
            style="width:100%"
          >
            <el-table-column prop="column_name" label="字段" min-width="160" />
            <el-table-column prop="data_type" label="类型" width="120" />
            <el-table-column prop="column_key" label="键" width="72" />
          </el-table>
          <div v-else-if="!holoColumnsLoading" style="color:#909399;font-size:13px">选表后自动加载字段</div>
          <div v-if="holoTargetColumns.length" style="margin-top:8px;font-size:12px;color:#909399">
            ODS 目标列（{{ holoTargetColumns.length }}）：{{ holoTargetColumns.slice(0, 8).join(', ') }}
            <span v-if="holoTargetColumns.length > 8">…</span>
          </div>
        </div>
        <el-button
          type="primary"
          @click="step = 1"
          :disabled="!holoSchema || !selectedTable || !!holoColumnsError || holoColumnsLoading || !holoColumns.length"
        >
          下一步：预览并创建 Holo SQL
        </el-button>
      </el-card>

      <el-card v-if="step === 1" header="Hologres SQL → MC 外表">
        <el-descriptions border :column="2">
          <el-descriptions-item label="Holo 读端">{{ holoReadRef }}</el-descriptions-item>
          <el-descriptions-item label="MC 外表">cda.{{ targetTable }}</el-descriptions-item>
          <el-descriptions-item label="MC 表">dataworks.{{ targetTable }}</el-descriptions-item>
          <el-descriptions-item label="字段">{{ holoColumns.length || holoPreviewMeta.column_count }} 列</el-descriptions-item>
          <el-descriptions-item label="节点路径">
            <span style="color:#409EFF">{{ scriptPath }}/{{ targetTable }}</span>
            <el-button size="small" style="margin-left:8px" @click="showTree = !showTree">{{ showTree ? '收起' : '更换' }}</el-button>
          </el-descriptions-item>
          <el-descriptions-item label="调度分钟">
            <el-input-number v-model="scheduleMinute" :min="0" :max="59" controls-position="right" />
          </el-descriptions-item>
        </el-descriptions>
        <el-alert type="info" :closable="false" style="margin:12px 0" title="节点创建后不自动发布；请在 DataWorks 核对脚本后自行发布" />
        <el-alert type="warning" :closable="false" style="margin:12px 0" title="严禁 select *：元数据缺失时将拒绝预览/创建，请先补全 Holo 字段或仓库 ODS DDL" />
        <div style="margin-bottom:12px">
          <el-button @click="previewHoloDml" :loading="previewingHolo">预览 DML</el-button>
          <el-tag v-if="holoPreviewMeta.column_count" type="success" style="margin-left:8px">{{ holoPreviewMeta.column_count }} 列</el-tag>
        </div>
        <CodeBlock v-if="holoPreviewText" style="margin-top:12px">{{ holoPreviewText }}</CodeBlock>
        <div v-if="holoPreviewParams.length" style="margin-top:12px">
          <div style="font-size:13px;color:#606266;margin-bottom:6px">调度参数（{{ holoPreviewParams.length }}）</div>
          <el-tag v-for="p in holoPreviewParams" :key="p.name" size="small" style="margin:0 6px 6px 0">{{ p.name }}</el-tag>
        </div>
        <div v-if="showTree" style="margin-top:12px;border:1px solid #eee;padding:12px;max-height:300px;overflow-y:auto">
          <div style="margin-bottom:8px;color:#999">
            <span v-if="treePath">当前: {{ treePath || '根目录' }}</span>
            <el-button v-if="treePath" size="small" style="margin-left:8px" @click="loadTree(parentPath(treePath))">上一级</el-button>
            <el-button size="small" type="primary" @click="selectPath(treePath || 'dataworks_agent')">选此目录</el-button>
          </div>
          <div v-for="node in treeNodes" :key="node.uuid" style="padding:6px 0;cursor:pointer;border-bottom:1px solid #f5f5f5"
               @click="node.type === 'folder' ? loadTree(node.path) : null">
            <span>{{ node.type === 'folder' ? '📁' : '📄' }}</span>
            <span style="margin-left:4px">{{ node.name }}</span>
          </div>
          <div v-if="treeLoading" style="color:#999">加载中...</div>
        </div>
        <div style="margin-top:16px">
          <el-button @click="step = 0">上一步</el-button>
          <el-button type="primary" @click="createHoloNode" :loading="creatingHolo">创建 Holo SQL 节点</el-button>
          <el-button type="success" @click="finish">完成</el-button>
        </div>
      </el-card>
    </template>

    <!-- ========== DI 抽取 ========== -->
    <template v-if="odsPath === 'di'">
      <el-steps :active="step" align-center style="margin-bottom:24px">
        <el-step title="选表" description="MySQL / PolarDB 等" />
        <el-step title="DI 节点" description="Reader → MC ODS" />
      </el-steps>

      <el-card v-if="step === 0">
        <el-alert type="info" :closable="false" style="margin-bottom:16px">
          <template #title>链路 ②：ODS DI（ods_ms_ / ods_pl_ 等）</template>
          <div style="font-size:13px;line-height:1.6">
            <p style="margin:0 0 6px">外部库（MySQL、PolarDB…）→ <strong>数据集成</strong> → MC <code>dataworks_dev.ods_*</code> → <code>insert</code> 到 <code>dataworks</code>。</p>
            <p style="margin:0;color:#909399">典型：shopplus、material 等，表名前缀 <code>ods_ms_</code> / <code>ods_pl_</code>。</p>
          </div>
        </el-alert>
        <el-row :gutter="16">
          <el-col :span="6">
            <el-form-item label="数据源类型">
              <el-select v-model="dsTypeFilter" @change="loadDataSources" style="width:100%">
                <el-option value="" label="全部" />
                <el-option value="mysql" label="MySQL" />
                <el-option value="polardb" label="PolarDB" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="Reader 数据源">
              <el-select v-model="dsName" placeholder="选择数据源" @change="onDSChange" filterable style="width:100%">
                <el-option v-for="ds in dataSources" :key="ds.name" :label="`${ds.name} (${ds.type_label || ds.type})`" :value="ds.name" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="源表">
              <el-select v-if="dsName" v-model="selectedTable" placeholder="选择表" filterable style="width:100%">
                <el-option v-for="t in dsTables" :key="t.name" :label="t.name" :value="t.name" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="粒度">
              <el-select v-model="granularity" style="width:100%">
                <el-option value="hour" label="小时" />
                <el-option value="day" label="天" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-checkbox v-model="withInitialization">启用 init + 增量双 DI 任务</el-checkbox>
          </el-col>
        </el-row>
        <el-button type="primary" @click="step = 1" :disabled="!selectedTable">下一步：创建 DI</el-button>
      </el-card>

      <el-card v-if="step === 1" header="创建 DI 节点">
        <el-descriptions border :column="2">
          <el-descriptions-item label="Reader">{{ dsName }}.{{ selectedTable }}</el-descriptions-item>
          <el-descriptions-item label="Writer">dataworks.{{ targetTable }}</el-descriptions-item>
          <el-descriptions-item label="节点路径">{{ scriptPath }}/{{ targetTable }}</el-descriptions-item>
          <el-descriptions-item label="资源组">{{ resourceGroup }}</el-descriptions-item>
        </el-descriptions>
        <div style="margin-top:16px">
          <el-button @click="step = 0">上一步</el-button>
          <el-button type="primary" @click="createDINode()" :loading="creating">创建 DI 节点</el-button>
        </div>
      </el-card>
    </template>

    <!-- ========== 纯 MC（dataworks_develop） ========== -->
    <template v-if="odsPath === 'mc'">
      <el-card header="链路 ③：ODS MC（dataworks_develop 取数）">
        <el-alert type="info" :closable="false" style="margin-bottom:16px">
          <div style="font-size:13px;line-height:1.6">
            <p style="margin:0 0 6px">源表已在 MC <code>dataworks.dataworks_develop.*</code>（如 <code>rule_adset_info</code>），<strong>不经 Holo、不经外部 DI Reader</strong>。</p>
            <p style="margin:0 0 6px"><b>典型 DML</b>：<code>insert overwrite dataworks_dev.ods_* … from dataworks.dataworks_develop.*</code>，再 <code>dataworks_dev → dataworks</code>。</p>
            <p style="margin:0;color:#909399">JSON 源表若要走 Holo 解析 + 回写，见「新建建模」或 Holo JSON 全链路；此处是<strong>纯 ODPS SQL / MC Reader DI</strong>。</p>
          </div>
        </el-alert>
        <el-form-item label="搜索 dataworks_develop 源表">
          <el-select
            v-model="mcSourceTable"
            filterable
            remote
            :remote-method="searchMcSource"
            :loading="mcSearching"
            placeholder="输入 rule_ / landing_ 等关键词…"
            style="width:100%"
          >
            <el-option
              v-for="t in mcSourceOptions"
              :key="t.table_name"
              :label="`${t.project || 'dataworks'}.${t.table_name}`"
              :value="`${t.project || 'dataworks'}.${t.table_name}`"
            >
              <span>{{ t.project || 'dataworks' }}.{{ t.table_name }}</span>
              <span style="float:right;color:#999;font-size:12px">{{ t.comment }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-descriptions v-if="mcSourceTable" border :column="1" style="margin-top:12px">
          <el-descriptions-item label="源表">{{ mcSourceTable }}</el-descriptions-item>
          <el-descriptions-item label="建议 ODS 名">{{ mcTargetTableSuggestion }}</el-descriptions-item>
          <el-descriptions-item label="文件顺序">dataworks DDL → dataworks_dev DDL → dev 从 develop 取数 → dev→dataworks → DWD</el-descriptions-item>
        </el-descriptions>
        <div style="margin-top:16px">
          <el-button type="primary" :disabled="!mcSourceTable" @click="$router.push({ path: '/tasks/create' })">
            前往「新建建模」生成 ODS/DWD
          </el-button>
          <el-button @click="searchMcSource('rule_')">示例：rule_ 表</el-button>
        </div>
      </el-card>
    </template>

    <!-- ========== OSS 导入 ========== -->
    <template v-if="odsPath === 'oss'">
      <el-card header="OSS 数据导入">
        <el-alert type="info" :closable="false" style="margin-bottom:16px">
          <div style="font-size:13px;line-height:1.6">
            <p style="margin:0 0 6px">从 OSS 文件导入数据到 ODS 表（CSV / Parquet）。</p>
            <p style="margin:0;color:#909399">三方数据通常先进入 <code>dataworks</code> 的 ODS。</p>
          </div>
        </el-alert>
        <el-form label-width="110px" inline>
          <el-form-item label="OSS 路径"><el-input v-model="ossForm.oss_path" style="width:280px" /></el-form-item>
          <el-form-item label="目标表"><el-input v-model="ossForm.target_table" style="width:220px" /></el-form-item>
          <el-form-item label="格式">
            <el-select v-model="ossForm.file_format" style="width:100px">
              <el-option value="csv" label="csv" />
              <el-option value="json" label="json" />
              <el-option value="parquet" label="parquet" />
            </el-select>
          </el-form-item>
          <el-form-item label="通配符"><el-input v-model="ossForm.wildcard" style="width:120px" /></el-form-item>
          <el-form-item label="调度粒度">
            <el-select v-model="ossForm.schedule_type" style="width:100px">
              <el-option value="day" label="天" />
              <el-option value="hour" label="小时" />
            </el-select>
          </el-form-item>
          <el-form-item label="发布"><el-switch v-model="ossForm.publish" /></el-form-item>
          <el-button type="primary" @click="addOss">加入列表</el-button>
          <el-button @click="previewOss" :loading="ossPreviewing">预览 SQL</el-button>
        </el-form>
        <el-table :data="ossList" border size="small" style="margin-top:12px">
          <el-table-column prop="oss_path" label="OSS 路径" />
          <el-table-column prop="target_table" label="目标表" width="200" />
          <el-table-column prop="file_format" label="格式" width="80" />
          <el-table-column label="操作" width="80">
            <template #default="{ $index }">
              <el-button link type="danger" @click="ossList.splice($index, 1)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div style="margin-top:12px">
          <el-button type="success" @click="submitOssBatch" :loading="ossSubmitting" :disabled="!ossList.length">提交 OSS 批次</el-button>
        </div>
      </el-card>
    </template>

    <!-- ========== 实时 ODS ========== -->
    <template v-if="odsPath === 'realtime'">
      <el-card header="实时 ODS 同步">
        <el-alert type="info" :closable="false" style="margin-bottom:16px">
          <div style="font-size:13px;line-height:1.6">
            <p style="margin:0 0 6px">通过 DataWorks 实时数据集成，从数据源 binlog 同步到 Holo 或 MC。</p>
            <p style="margin:0;color:#909399">需要先在 DataWorks 配置好实时同步任务。</p>
          </div>
        </el-alert>
        <el-form label-width="110px">
          <el-row :gutter="16">
            <el-col :span="8"><el-form-item label="库名"><el-input v-model="rtForm.database_schema" /></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="表名"><el-input v-model="rtForm.table_name" /></el-form-item></el-col>
            <el-col :span="8">
              <el-form-item label="粒度">
                <el-select v-model="rtForm.granularity" style="width:100%">
                  <el-option value="hour" label="小时" />
                  <el-option value="day" label="天" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="SELECT DML">
            <el-input v-model="rtForm.select_dml" type="textarea" :rows="3" placeholder="可选，留空则从 sync_rows 推断" />
          </el-form-item>
          <el-form-item label="sync_rows (JSON)">
            <el-input v-model="rtSyncRowsJson" type="textarea" :rows="4" placeholder='[{"field":"value"}]' />
          </el-form-item>
          <el-form-item label="发布"><el-switch v-model="rtForm.publish" /></el-form-item>
          <div style="margin-top:12px">
            <el-button @click="previewRealtime" :loading="rtPreviewing">预览</el-button>
            <el-button type="success" @click="submitRealtimeBatch" :loading="rtSubmitting">提交实时批次</el-button>
          </div>
        </el-form>
      </el-card>
    </template>

    <!-- ========== 批量部署 ========== -->
    <template v-if="odsPath === 'batch'">
      <el-card header="批量部署 ODS/DWD 表">
        <el-alert type="info" :closable="false" style="margin-bottom:16px">
          <div style="font-size:13px;line-height:1.6">
            <p style="margin:0 0 6px">批量部署 ODS/DWD 表：解析 DDL 文件 → MC 建表(dev+prod) → 创建节点 → 配置调度。</p>
            <p style="margin:0;color:#909399">已存在的节点会自动跳过（断点续传）。</p>
          </div>
        </el-alert>
        <el-form label-width="110px">
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="层类型">
                <el-select v-model="batchForm.layer" style="width:100%">
                  <el-option value="ODS" label="ODS (Holo SQL)" />
                  <el-option value="DWD" label="DWD (ODPS SQL)" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="节点目录">
                <el-input v-model="batchForm.node_path" placeholder="dataworks_agent/01_ODS" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="DDL 目录">
            <el-input v-model="batchForm.ddl_dir" placeholder="E:\dw-modeling-template\sql\...\ddl" style="width:100%" />
          </el-form-item>
          <el-form-item label="DML 目录">
            <el-input v-model="batchForm.dml_dir" placeholder="E:\dw-modeling-template\sql\...\dml（可选）" style="width:100%" />
          </el-form-item>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="MC 项目">
                <el-input v-model="batchForm.mc_project" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="MC Dev 项目">
                <el-input v-model="batchForm.mc_dev_project" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="调度分钟">
                <el-input-number v-model="batchForm.schedule_minute" :min="0" :max="59" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-button type="primary" @click="batchDeploy" :loading="batchDeploying">批量部署</el-button>
        </el-form>

        <!-- 部署结果 -->
        <div v-if="batchResult" style="margin-top:16px">
          <el-alert
            :type="batchResult.failed === 0 ? 'success' : 'warning'"
            :closable="false"
            show-icon
          >
            <template #title>
              部署完成：{{ batchResult.success }}/{{ batchResult.total }} 成功
              <span v-if="batchResult.failed > 0">，{{ batchResult.failed }} 失败</span>
            </template>
          </el-alert>
          <el-table :data="batchResult.results" size="small" border style="margin-top:12px" max-height="400">
            <el-table-column prop="table" label="表名" min-width="200" />
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.success ? 'success' : 'danger'" size="small">
                  {{ row.success ? 'OK' : 'FAIL' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="详情" min-width="200">
              <template #default="{ row }">
                <span v-if="row.steps.skipped">跳过（已存在）</span>
                <span v-else-if="row.steps.node?.status === 'ok'">UUID: {{ row.steps.node.uuid }}</span>
                <span v-else-if="row.error" style="color:#F56C6C">{{ row.error }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-card>
    </template>

    <div v-if="result.msg" style="margin-top:16px">
      <el-alert :type="result.ok ? 'success' : 'error'" :title="result.msg" :closable="false" />
    </div>
    <div v-if="ensureResult" style="margin-top:12px">
      <el-alert
        :type="ensureResult.status === 'created' ? 'success' : ensureResult.status === 'exists' ? 'info' : ensureResult.status === 'incompatible' ? 'warning' : 'error'"
        :closable="false"
        show-icon
      >
        <template #title>
          <span v-if="ensureResult.status === 'created'">建表完成</span>
          <span v-else-if="ensureResult.status === 'exists'">表已存在（跳过建表）</span>
          <span v-else-if="ensureResult.status === 'incompatible'">表结构不兼容</span>
          <span v-else>建表失败</span>
          <el-tag v-if="ensureResult.ddl_source" size="small" style="margin-left:8px">
            {{ ensureResult.ddl_source === 'registry' ? 'DDL registry' : '动态生成' }}
          </el-tag>
          <el-tag v-if="ensureResult.holo_note" type="warning" size="small" style="margin-left:4px">{{ ensureResult.holo_note }}</el-tag>
        </template>
        <template #default>
          <div v-if="ensureResult.environments" style="font-size:13px;line-height:1.8">
            <div v-for="(env, name) in ensureResult.environments" :key="name">
              <el-tag :type="env.status === 'created' ? 'success' : env.status === 'exists' ? 'info' : 'danger'" size="small">
                {{ name }}
              </el-tag>
              {{ env.project }}.
              <span v-if="env.status === 'created'">新建成功</span>
              <span v-else-if="env.status === 'exists'">已存在</span>
              <span v-else-if="env.status === 'incompatible'" style="color:#E6A23C">结构不兼容</span>
              <span v-else style="color:#F56C6C">{{ env.error || '失败' }}</span>
            </div>
          </div>
          <span v-if="ensureResult.error" style="color:#F56C6C">{{ ensureResult.error }}</span>
        </template>
      </el-alert>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { request } from '@/utils/request'
import { DataBoard, Connection, Coin, Upload, Timer } from '@element-plus/icons-vue'
import CodeBlock from '@/components/CodeBlock.vue'

const METADATA_SOURCE_LABEL: Record<string, string> = {
  snapshot: 'schema 快照',
  ddl_registry: 'ODS DDL 登记',
  local_template: '本地 SQL 模板',
  mc_ods_ddl: 'MC 已建 ODS 表',
  inferred: '字段推断',
}
const HOLO_INSTANCE = 'cda_giiktok_hologres'

const odsPath = ref<'holo' | 'di' | 'mc' | 'oss' | 'realtime' | 'batch'>('holo')
const step = ref(0)
const holoSchema = ref('')
const holoSchemas = ref<string[]>(['ofc', 'oms', 'gimp'])
const holoTables = ref<{ name: string }[]>([])
const holoTablesLoading = ref(false)
const holoTableSource = ref('')
const holoColumns = ref<{ column_name: string; data_type: string; column_key: string }[]>([])
const holoTargetColumns = ref<string[]>([])
const holoColumnsLoading = ref(false)
const holoColumnsError = ref('')
const holoColumnMeta = ref({ metadata_source: '', split_pk: '', where_field: '' })
const holoWhereMode = ref('auto')
const holoWhereOptions = ref<{ mode: string; label: string }[]>([])
const dsName = ref('')
const dsType = ref('')
const selectedTable = ref('')
const granularity = ref('hour')
const resourceGroup = ref('')
const withInitialization = ref(false)
const initOptions = ref({
  dev_mc_project: '',
  prod_mc_project: '',
  init_partition_date: '20170101',
  init_partition_hour: '00',
  allow_empty_source: false,
  publish_incremental_after_init: true,
  first_incremental_lookback_hours: null as number | null,
})
const dsTypeFilter = ref('')
const dataSources = ref<any[]>([])
const dsTables = ref<any[]>([])
const dsTablesLoading = ref(false)
const creating = ref(false)
const creatingHolo = ref(false)
const previewingHolo = ref(false)
const holoPreviewText = ref('')
const holoPreviewMeta = ref({ column_count: 0 })
const holoPreviewParams = ref<{ name: string }[]>([])
const scheduleMinute = ref(1)
const result = ref({ ok: false, msg: '' })
const ensureResult = ref<{ status: string; ddl_source?: string; holo_note?: string; error?: string; environments?: Record<string, { status: string; project?: string; error?: string }> } | null>(null)
const showTree = ref(false)
const scriptPath = ref('dataworks_agent/01_ODS')
const treePath = ref('')
const treeNodes = ref<any[]>([])
const treeLoading = ref(false)
const mcSourceTable = ref('')
const mcSourceOptions = ref<any[]>([])
const mcSearching = ref(false)

const TYPE_PREFIX: Record<string, string> = {
  mysql: 'ms',
  polardb: 'pl',
  postgresql: 'pg',
  hologres: 'hl',
  maxcompute: 'mc',
  odps: 'mc',
}

const targetTable = computed(() => {
  if (!selectedTable.value) return ''
  const suffix = { hour: 'hour', day: 'day', min: 'min' }[granularity.value] || 'hour'
  if (odsPath.value === 'holo') {
    return `ods_hl_${holoSchema.value}__${selectedTable.value}_${suffix}`
  }
  const prefix = TYPE_PREFIX[dsType.value] || 'ms'
  return `ods_${prefix}_${dsName.value}__${selectedTable.value}_${suffix}`
})

const holoReadRef = computed(() => {
  if (!holoSchema.value || !selectedTable.value) return ''
  return `${holoSchema.value}.${selectedTable.value}`
})

const mcTargetTableSuggestion = computed(() => {
  if (!mcSourceTable.value) return ''
  const bare = mcSourceTable.value.split('.').pop() || ''
  return `ods_mc_dataworks_develop__${bare}_day（示例，按规范调整）`
})

function onPathChange() {
  step.value = 0
  result.value = { ok: false, msg: '' }
  selectedTable.value = ''
  if (odsPath.value === 'holo') {
    loadHoloSchemaList()
  } else {
    dsTypeFilter.value = odsPath.value === 'di' ? 'mysql' : ''
    loadDataSources()
  }
}

async function loadHoloSchemaList() {
  try {
    const r = await request<{ schemas: string[] }>('/api/workspace/holo/schemas')
    if (r.schemas?.length) holoSchemas.value = r.schemas
  } catch {
    /* keep defaults */
  }
}

async function loadHoloTables() {
  selectedTable.value = ''
  holoTables.value = []
  holoTableSource.value = ''
  holoColumns.value = []
  holoTargetColumns.value = []
  holoColumnsError.value = ''
  holoColumnMeta.value = { metadata_source: '', split_pk: '', where_field: '' }
  holoWhereMode.value = 'auto'
  holoWhereOptions.value = []
  if (!holoSchema.value) return
  holoTablesLoading.value = true
  try {
    const r = await request<{ tables: { name: string }[]; source: string }>(
      `/api/workspace/holo/schemas/${encodeURIComponent(holoSchema.value)}/tables`,
    )
    holoTables.value = r.tables || []
    holoTableSource.value = r.source || ''
  } catch {
    holoTables.value = []
  }
  holoTablesLoading.value = false
}

async function pickHoloSchema(name: string) {
  holoSchema.value = name
  await loadHoloTables()
}

async function loadHoloColumns() {
  if (!holoSchema.value || !selectedTable.value) return
  holoColumnsLoading.value = true
  holoColumnsError.value = ''
  holoColumns.value = []
  holoTargetColumns.value = []
  try {
    const r = await request<{
      source_columns: { column_name: string; data_type: string; column_key: string }[]
      target_columns: string[]
      metadata_source: string
      split_pk: string
      where_field: string
      default_where_mode: string
      where_options: { mode: string; label: string }[]
    }>(
      `/api/workspace/holo/schemas/${encodeURIComponent(holoSchema.value)}/tables/${encodeURIComponent(selectedTable.value)}/columns?granularity=${encodeURIComponent(granularity.value)}&where_mode=${encodeURIComponent(holoWhereMode.value)}`,
    )
    holoColumns.value = r.source_columns || []
    holoTargetColumns.value = r.target_columns || []
    holoWhereOptions.value = r.where_options || []
    if (holoWhereMode.value === 'auto' && r.default_where_mode) {
      holoWhereMode.value = r.default_where_mode
    }
    holoColumnMeta.value = {
      metadata_source: r.metadata_source || '',
      split_pk: r.split_pk || '',
      where_field: r.where_field || '',
    }
  } catch (e: any) {
    holoColumnsError.value = e.message || '字段加载失败'
  }
  holoColumnsLoading.value = false
}

async function onHoloWhereModeChange() {
  await loadHoloColumns()
}

watch([selectedTable, granularity], () => {
  if (odsPath.value === 'holo' && selectedTable.value) {
    loadHoloColumns()
  }
})

async function loadDataSources() {
  const q = dsTypeFilter.value ? `?type=${encodeURIComponent(dsTypeFilter.value)}` : ''
  try {
    const r = await request<{ datasources: any[] }>(`/api/workspace/datasources${q}`)
    dataSources.value = r.datasources || []
  } catch {
    dataSources.value = []
  }
}

async function onDSChange(name: string) {
  dsTablesLoading.value = true
  selectedTable.value = ''
  const ds = dataSources.value.find((d: any) => d.name === name)
  dsType.value = ds?.type || ''
  try {
    const r = await request<{ tables: any[] }>(`/api/workspace/datasources/${encodeURIComponent(name)}/tables`)
    dsTables.value = r.tables || []
  } catch {
    dsTables.value = []
  }
  dsTablesLoading.value = false
}

async function searchMcSource(keyword: string) {
  if (!keyword || keyword.length < 2) return
  mcSearching.value = true
  try {
    const r = await request<{ tables: any[] }>(`/api/workspace/search-tables?keyword=${encodeURIComponent(keyword)}`)
    mcSourceOptions.value = (r.tables || []).filter(
      (t: any) => (t.table_name || '').includes('develop') || (t.project || '').includes('develop') || keyword.length >= 3,
    )
  } catch {
    mcSourceOptions.value = []
  }
  mcSearching.value = false
}

function selectPath(path: string) {
  scriptPath.value = path
  showTree.value = false
}

async function loadTree(path: string = '') {
  treeLoading.value = true
  treePath.value = path
  try {
    const r = await request<{ nodes: any[] }>(`/api/workspace/repository-tree?path=${encodeURIComponent(path)}`)
    treeNodes.value = r.nodes || []
  } catch {
    treeNodes.value = []
  }
  treeLoading.value = false
}

function parentPath(p: string): string {
  const parts = p.split('/')
  parts.pop()
  return parts.join('/')
}

async function createDINode(sourceTypeOverride?: string) {
  creating.value = true
  try {
    const body: Record<string, unknown> = {
      datasource_name: odsPath.value === 'holo' ? holoSchema.value : dsName.value,
      table_name: selectedTable.value,
      script_path: scriptPath.value,
      granularity: granularity.value,
      resource_group: resourceGroup.value,
      with_initialization: withInitialization.value,
      source_type: sourceTypeOverride || dsType.value || 'mysql',
    }
    if (withInitialization.value) {
      body.initialization = { ...initOptions.value }
    }
    const r = await request<any>('/api/workspace/create-di-node', { method: 'POST', body })
    if (withInitialization.value) {
      const initOk = r.initialization?.success
      const incOk = r.incremental?.success
      result.value = {
        ok: r.status === 'ok',
        msg: `Init: ${initOk ? '成功' : '失败'} | 增量: ${incOk ? '成功' : '失败'} | ${r.target_table || targetTable.value}`,
      }
    } else {
      result.value = { ok: true, msg: `DI 节点 ${r.target_table || targetTable.value} 创建成功` }
    }
  } catch (e: any) {
    result.value = { ok: false, msg: `DI 创建失败: ${e.message}` }
  }
  creating.value = false
}

async function previewHoloDml() {
  previewingHolo.value = true
  holoPreviewText.value = ''
  holoPreviewParams.value = []
  try {
    const r = await request<any>('/api/workspace/preview-holo-dml', {
      method: 'POST',
      body: {
        holo_schema: holoSchema.value,
        table_name: selectedTable.value,
        granularity: granularity.value,
        where_mode: holoWhereMode.value,
      },
    })
    holoPreviewText.value = r.dml || ''
    holoPreviewMeta.value = { column_count: r.column_count || 0 }
    holoPreviewParams.value = r.parameters || []
  } catch (e: any) {
    result.value = { ok: false, msg: `预览失败: ${e.message}` }
  }
  previewingHolo.value = false
}

async function createHoloNode() {
  creatingHolo.value = true
  ensureResult.value = null
  try {
    const r = await request<{ status: string; action?: string; table: string; uuid: string; ensure_table?: { status: string; ddl_source?: string; holo_note?: string; error?: string; environments?: Record<string, { status: string; project?: string; error?: string }> } }>(
      '/api/workspace/create-holo-node',
      {
        method: 'POST',
        body: {
          holo_schema: holoSchema.value,
          table_name: selectedTable.value,
          script_path: scriptPath.value,
          granularity: granularity.value,
          schedule_minute: scheduleMinute.value,
          resource_group: resourceGroup.value,
          where_mode: holoWhereMode.value,
        },
      },
    )
    ensureResult.value = r.ensure_table || null
    const actionLabel = r.action === 'updated' ? '更新' : '创建'
    result.value = { ok: true, msg: `Holo SQL ${r.table} ${actionLabel}成功，请自行发布 (UUID: ${r.uuid})` }
  } catch (e: any) {
    result.value = { ok: false, msg: `Holo SQL 创建失败: ${e.message}` }
  }
  creatingHolo.value = false
}

function finish() {
  step.value = 0
  selectedTable.value = ''
  holoSchema.value = ''
  dsName.value = ''
  result.value = { ok: true, msg: 'ODS Holo 流程完成' }
}

// ── OSS 导入 ──
const ossForm = ref({
  oss_path: '',
  target_table: '',
  file_format: 'csv',
  wildcard: '',
  schedule_type: 'day',
  publish: true,
})
const ossList = ref<any[]>([])
const ossSubmitting = ref(false)
const ossPreviewing = ref(false)

function addOss() {
  if (!ossForm.value.oss_path || !ossForm.value.target_table) {
    result.value = { ok: false, msg: '请填写 OSS 路径和目标表' }
    return
  }
  ossList.value.push({ ...ossForm.value })
  ossForm.value.oss_path = ''
  ossForm.value.target_table = ''
}

async function previewOss() {
  ossPreviewing.value = true
  try {
    const r = await request<{ sql: string }>('/api/pipeline/preview/oss-sql', { method: 'POST', body: { ...ossForm.value } })
    result.value = { ok: true, msg: r.sql }
  } catch (e: any) {
    result.value = { ok: false, msg: `预览失败: ${e.message}` }
  }
  ossPreviewing.value = false
}

async function submitOssBatch() {
  if (!ossList.value.length) {
    result.value = { ok: false, msg: '请先加入至少一条 OSS 任务' }
    return
  }
  ossSubmitting.value = true
  try {
    const r = await request<{ batch_id: string; status: string }>('/api/pipeline/oss/batch', {
      method: 'POST',
      body: { submissions: ossList.value, run_immediately: true },
    })
    result.value = { ok: true, msg: `OSS 批次 ${r.batch_id} 已提交 (${r.status})` }
    ossList.value = []
  } catch (e: any) {
    result.value = { ok: false, msg: `提交失败: ${e.message}` }
  }
  ossSubmitting.value = false
}

// ── 实时 ODS ──
const rtForm = ref({
  database_schema: '',
  table_name: '',
  select_dml: '',
  granularity: 'hour',
  publish: true,
})
const rtSyncRowsJson = ref('[]')
const rtSubmitting = ref(false)
const rtPreviewing = ref(false)

async function previewRealtime() {
  rtPreviewing.value = true
  try {
    const sync_rows = JSON.parse(rtSyncRowsJson.value || '[]')
    const r = await request<Record<string, unknown>>('/api/pipeline/preview/realtime', {
      method: 'POST',
      body: { ...rtForm.value, sync_rows },
    })
    result.value = { ok: true, msg: JSON.stringify(r, null, 2) }
  } catch (e: any) {
    result.value = { ok: false, msg: `预览失败: ${e.message}` }
  }
  rtPreviewing.value = false
}

async function submitRealtimeBatch() {
  rtSubmitting.value = true
  try {
    const sync_rows = JSON.parse(rtSyncRowsJson.value || '[]')
    const r = await request<{ batch_id: string; status: string }>('/api/pipeline/realtime/batch', {
      method: 'POST',
      body: { submissions: [{ ...rtForm.value, sync_rows }], run_immediately: true },
    })
    result.value = { ok: true, msg: `实时批次 ${r.batch_id} 已提交 (${r.status})` }
  } catch (e: any) {
    result.value = { ok: false, msg: `提交失败: ${e.message}` }
  }
  rtSubmitting.value = false
}

// ── 批量部署 ──
const batchForm = ref({
  layer: 'ODS',
  ddl_dir: '',
  dml_dir: '',
  node_path: 'dataworks_agent/01_ODS',
  mc_project: 'dataworks',
  mc_dev_project: 'dataworks_dev',
  schedule_minute: 1,
})
const batchDeploying = ref(false)
const batchResult = ref<any>(null)

async function batchDeploy() {
  if (!batchForm.value.ddl_dir) {
    result.value = { ok: false, msg: '请填写 DDL 目录' }
    return
  }
  batchDeploying.value = true
  batchResult.value = null
  try {
    batchResult.value = await request('/api/deploy/batch-deploy', {
      method: 'POST',
      body: batchForm.value,
    })
    result.value = { ok: true, msg: `批量部署完成：${batchResult.value.success}/${batchResult.value.total}` }
  } catch (e: any) {
    result.value = { ok: false, msg: `批量部署失败: ${e.message}` }
  }
  batchDeploying.value = false
}

onMounted(() => {
  if (odsPath.value === 'holo') {
    loadHoloSchemaList()
  } else {
    loadDataSources()
  }
})
</script>
