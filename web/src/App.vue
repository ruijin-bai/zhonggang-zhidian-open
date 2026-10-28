<template>
  <ElConfigProvider :locale="zhCn" :empty-values="[null, undefined]" :value-on-clear="null"><router-view /></ElConfigProvider>
</template>

<script setup lang="ts">
import { ElConfigProvider } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
</script>
