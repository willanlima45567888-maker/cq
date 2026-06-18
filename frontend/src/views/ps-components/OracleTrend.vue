<script setup lang="ts">
/**
 * Oracle 进程趋势（多线图）
 * 显示 Oracle 总数 / PX / Job 随时间变化
 */
import { onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { PsTrends } from '../../api/ps'

const props = defineProps<{
  trends: PsTrends
}>()

const chartRef = ref<HTMLDivElement | null>(null)
let chartInstance: echarts.ECharts | null = null

function buildOptions() {
  const mkSeries = (name: string, color: string, data: number[]) => ({
    name,
    type: 'line' as const,
    data: props.trends.timestamps.map((ts, i) => [ts, data[i]]),
    showSymbol: false,
    smooth: false,
    lineStyle: { width: 1.8, color },
    itemStyle: { color },
  })
  return {
    tooltip: { trigger: 'axis' as const, axisPointer: { type: 'cross' as const } },
    legend: { top: 0, type: 'scroll' as const },
    xAxis: { type: 'time' as const, axisLabel: { fontSize: 11 } },
    yAxis: { type: 'value' as const, name: '进程数', axisLabel: { fontSize: 11 } },
    dataZoom: [
      { type: 'inside' as const, start: 0, end: 100 },
      { type: 'slider' as const, start: 0, end: 100, height: 18, bottom: 0 },
    ],
    grid: { top: 36, right: 30, bottom: 50, left: 60 },
    series: [
      mkSeries('Oracle 总数', '#dc2626', props.trends.oracle),
      mkSeries('PX 并行', '#ea580c', props.trends.px),
      mkSeries('Job', '#7c3aed', props.trends.job),
    ],
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
  height: 280px;
  background: white;
  border-radius: 8px;
  padding: 8px;
}
</style>
