<template>
  <header class="page-head zg-page-header">
    <div class="page-heading">
      <span v-if="eyebrow" class="page-eyebrow">{{ eyebrow }}</span>
      <h1 class="zg-title">{{ title }}</h1>
      <p v-if="description" class="hint">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="page-actions"><slot name="actions" /></div>
  </header>
</template>

<script setup lang="ts">
defineProps<{ title: string; description?: string; eyebrow?: string }>()
</script>
