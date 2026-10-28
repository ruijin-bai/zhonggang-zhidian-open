<template>
  <section v-if="error" class="data-state data-error" role="alert">
    <strong>暂时无法加载</strong><p>{{ error }}</p>
    <el-button @click="$emit('retry')">重新加载</el-button>
  </section>
  <section v-else-if="empty" class="data-state">
    <strong>{{ emptyTitle || '暂无记录' }}</strong>
    <p v-if="emptyDescription">{{ emptyDescription }}</p>
    <slot name="actions" />
  </section>
  <slot v-else />
</template>

<script setup lang="ts">
defineProps<{ error?: string; empty?: boolean; emptyTitle?: string; emptyDescription?: string }>()
defineEmits<{ retry: [] }>()
</script>
