<template>
  <el-config-provider :locale="zhCn">
    <router-view />
  </el-config-provider>
</template>
<script setup lang="ts">
import { ElConfigProvider } from 'element-plus'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
</script>
<style>
:root { font-family: Inter, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; color: #29292f; background: #f5f5f7; font-synthesis: none; }
* { box-sizing: border-box; }
html, body, #app { min-width: 320px; min-height: 100%; margin: 0; }
button, textarea, input { font: inherit; }
</style>
