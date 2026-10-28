<template>
  <section class="followup">
    <div class="followup-head"><div class="title">为准确回答，请补充以下信息</div><span>还需 {{ follow_up.missing.length }} 项</span></div>
    <div v-for="p in follow_up.prompts" :key="p.slot" class="prompt">
      <span class="label">{{ p.label }}：</span>
      <el-radio-group v-model="selected[p.slot]">
        <el-radio-button v-for="opt in p.options" :key="opt" :value="opt">{{ opt }}</el-radio-button>
      </el-radio-group>
    </div>
    <el-button type="primary" :disabled="!allFilled" @click="submit">继续回答</el-button>
  </section>
</template>

<script setup lang="ts">
import { reactive, computed, watch } from 'vue'
import type { FollowUp } from '@/api/qa'

const props = defineProps<{ follow_up: FollowUp }>()
const emit = defineEmits<{ (e: 'answered', slots: Record<string, string>): void }>()

const selected = reactive<Record<string, string>>({})
const allFilled = computed(() => props.follow_up.missing.every((s) => selected[s]))
watch(() => props.follow_up, () => { Object.keys(selected).forEach((key) => delete selected[key]) })

function submit() {
  emit('answered', { ...selected })
}
</script>

<style scoped>
.followup { padding: 12px; margin: 12px 0; border: 1px solid var(--zg-border); border-left: 3px solid var(--zg-primary); background: #fff; }
.followup-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }.followup-head > span { color: var(--zg-text-weak); font-size: 12px; }.title { font-weight: 600; }
.prompt { margin-bottom: 10px; }
.label { margin-right: 8px; }
</style>
