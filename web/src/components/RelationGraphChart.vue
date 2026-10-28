<template>
  <div class="chart-container">
    <div v-if="hasLinks" ref="chartRef" class="chart"></div>
    <div v-else class="empty-graph">
      <div class="empty-icon">◇</div>
      <p>暂无制度关系数据</p>
      <span>在管理后台维护制度间的替代、从属、多制度约束或冲突关系后，此处将展示关系图谱</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch, computed } from 'vue'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ECharts } from 'echarts/core'
import type { GraphData } from '@/api/relation'

echarts.use([GraphChart, TooltipComponent, CanvasRenderer])

const props = defineProps<{ data: GraphData }>()
const chartRef = ref<HTMLDivElement | null>(null)
let chart: ECharts | null = null

const NODE_COLOR = '#005BAC'
const NODE_REPEALED = '#C0C4CC'
const NODE_REPLACED = '#92B9D8'
const EDGE_COLOR = '#A0A8B2'

const REL_COLOR: Record<string, string> = {
  replace: '#005BAC',
  subordinate: '#0e7a5c',
  multi_constraint: '#b77d18',
  conflict: '#a33a2b',
}
const REL_LABEL: Record<string, string> = {
  replace: '替代',
  subordinate: '从属',
  multi_constraint: '多制度约束',
  conflict: '冲突',
}

function truncate(name: string, max = 14): string {
  if (!name) return ''
  return name.length > max ? name.slice(0, max) + '…' : name
}

const hasLinks = computed(() => props.data.edges.length > 0)

function buildOption() {
  // Only include nodes that appear in at least one edge
  const edgeIds = new Set<string>()
  for (const e of props.data.edges) {
    edgeIds.add(e.from)
    edgeIds.add(e.to)
  }
  const nodes = props.data.nodes
    .filter((n) => edgeIds.has(n.id))
    .map((n) => ({
      id: n.id,
      name: truncate(n.title),
      fullName: n.title,
      version: n.version,
      symbolSize: 50,
      itemStyle: {
        color: n.status === 'repealed' ? NODE_REPEALED : n.status === 'replaced' ? NODE_REPLACED : NODE_COLOR,
      },
      label: { show: true, position: 'right', fontSize: 12, color: '#20252b' },
    }))
  const links = props.data.edges.map((e) => ({
    source: e.from,
    target: e.to,
    label: {
      show: true,
      formatter: REL_LABEL[e.type] || e.type,
      fontSize: 11,
      color: REL_COLOR[e.type] || EDGE_COLOR,
      backgroundColor: 'rgba(255,255,255,0.85)',
      padding: [2, 4],
      borderRadius: 2,
    },
    lineStyle: {
      color: REL_COLOR[e.type] || EDGE_COLOR,
      width: e.type === 'conflict' ? 2 : 1.5,
      type: e.type === 'conflict' ? 'dashed' : 'solid',
      curveness: 0.15,
    },
  }))
  return {
    tooltip: {
      formatter: (p: any) => {
        if (p.dataType === 'node') return p.data.fullName || p.data.name
        if (p.dataType === 'edge') return p.data.label.formatter
        return p.name
      },
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        force: { repulsion: 300, edgeLength: [120, 200], gravity: 0.1 },
        data: nodes,
        links,
        emphasis: {
          focus: 'adjacency',
          lineStyle: { width: 3 },
          label: { fontSize: 13 },
        },
      },
    ],
  }
}

function render() {
  if (!chart) return
  if (hasLinks.value) {
    chart.setOption(buildOption(), true)
  }
}

function ensureChart() {
  if (!chart && chartRef.value) {
    chart = echarts.init(chartRef.value)
    window.addEventListener('resize', handleResize)
  }
}

function handleResize() {
  chart?.resize()
}

onMounted(() => {
  if (hasLinks.value && chartRef.value) {
    ensureChart()
    render()
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
  chart = null
})

watch(() => props.data, () => {
  if (hasLinks.value) {
    ensureChart()
    render()
  }
}, { deep: true })
</script>

<style scoped>
.chart-container { width: 100%; }
.chart { width: 100%; height: 520px; background: #fff; border: 1px solid var(--zg-border); }
.empty-graph { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 520px; border: 1px solid var(--zg-border); background: #fff; }
.empty-icon { font-size: 32px; color: var(--zg-border); margin-bottom: 8px; }
.empty-graph p { margin: 0 0 4px; color: var(--zg-text-secondary); font-size: 14px; }
.empty-graph span { max-width: 320px; color: var(--zg-text-weak); font-size: 12px; text-align: center; line-height: 1.6; }
</style>
