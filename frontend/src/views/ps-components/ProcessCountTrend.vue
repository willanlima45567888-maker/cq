<script setup lang="ts">
/**
 * 进程总数趋势（多线图）
 * 显示 total / oracle / grid / kernel / user 5 条线随时间变化
 */
import { onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { PsTrends } from '../../api/ps'

const props = defineProps<{
  trends: PsTrends
  /** 要显示的曲线，默认 all */
  showLines?: ('total' | 'oracle' | 'grid' | 'kernel' | 'user')[]
}>()

const chartRef = ref<HTMLDivElement | null>(null)
let chartInstance: echarts.ECharts | null = null

const COLORS: Record<string, string> = {
  total: '#1f2937',
  oracle: '#dc2626',
  grid: '#16a34a',
  kernel: '#9ca3af',
  user: '#2563eb',
}

const NAMES: Record<string, string> = {
  total: '总进程',
  oracle: 'Oracle',
  grid: 'Grid',
  kernel: 'Kernel',
  user: '用户',
}

function buildOptions() {
  const lines = props.showLines ?? ['total', 'oracle', 'grid', 'kernel', 'user']
  const series = lines.map((k) => ({
    name: NAMES[k],
    type: 'line' as const,
    data: props.trends.timestamps.map((ts, i) => [ts, props.trends[k][i]]),
    showSymbol: false,
    smooth: false,
    lineStyle: { width: 1.5, color: COLORS[k] },
    itemStyle: { color: COLORS[k] },
  }))
  return {
    tooltip: {
      trigger: 'axis' as const,
      axisPointer: { type: 'cross' as const },
    },
    legend: { top: 0, type: 'scroll' as const, selectedMode: 'multiple' as const },
    xAxis: { type: 'time' as const, axisLabel: { fontSize: 11 } },
    yAxis: { type: 'value' as const, name: '进程数', axisLabel: { fontSize: 11 } },
    dataZoom: [
      { type: 'inside' as const, start: 0, end: 100 },
      { type: 'slider' as const, start: 0, end: 100, height: 18, bottom: 0 },
    ],
    grid: { top: 36, right: 30, bottom: 50, left: 60 },
    series,
  }
}

function initChart() {
  if (!chartRef.value) return
  if (chartInstance) chartInstance.dispose()
  chartInstance = echarts.init(chartRef.value)
  chartInstance.setOption(buildOptions())
}

onMounted(initChart)
watch(() => props.trends, initChart, { deep: true })
window.addEventListener('resize', () => chartInstance?.resize())
</script>

<template>
  <div ref="chartRef" class="chart" />
</template>

<style scoped>
.chart {
  width: 100%;
  height: 320px;
  background: white;
  border-radius: 8px;
  padding: 8px;
}
</style>
