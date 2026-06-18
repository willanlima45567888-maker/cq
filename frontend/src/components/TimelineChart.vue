<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

interface SeriesData {
  name: string
  data: [string, number][]
}

const props = defineProps<{
  title: string
  series: SeriesData[]
  unit?: string
  /** 值类型：integer=计数（整数，无小数）/ decimal=浮点（可有小数）*/
  valueType?: 'integer' | 'decimal'
  /** 点击图表上某个数据点时触发，回调收到该点的 timestamp 字符串 */
  onPointClick?: (timestamp: string) => void
  /** 图表高度（px），默认 300。多图布局时可设小一点 */
  height?: number
}>()

const chartRef = ref<HTMLDivElement | null>(null)
let chartInstance: echarts.ECharts | null = null

function buildOptions() {
  return {
    title: { text: props.title, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: {
      trigger: 'axis',
      formatter: (params: echarts.DefaultLabelFormatterCallbackParams[]) => {
        if (!params.length) return ''
        let result = `<strong>${params[0].axisValue}</strong><br/>`
        for (const p of params) {
          result += `${p.marker} ${p.seriesName}: <strong>${(p.value as [string, number])[1]}</strong>${props.unit || ''}<br/>`
        }
        return result
      }
    },
    legend: {
      top: 30,
      selectedMode: 'multiple',
      type: 'scroll',
    },
    xAxis: {
      type: 'time',
      name: '时间',
      nameLocation: 'end',
      nameGap: 18,
      nameTextStyle: { fontSize: 11, color: '#6b7280' },
      axisLabel: {
        fontSize: 11,
        // 自动间隔避免标签密密麻麻（echarts 内部用 0 / 'auto' / 函数）
        // 取 max(0, ceil(数据点数 / 8)) 让最多显示 8 个时间标签
        interval: 0,
        hideOverlap: true,
        rotate: 30,
        formatter: (val: number) => {
          // 只显示时间 HH:MM（日期范围已在外层 time-label 里展示）
          const d = new Date(val)
          const pad = (n: number) => String(n).padStart(2, '0')
          return `${pad(d.getHours())}:${pad(d.getMinutes())}`
        },
      },
    },
    yAxis: {
      type: 'value',
      name: props.unit ? `（单位：${props.unit}）` : '（单位：次数）',
      nameLocation: 'start',
      nameGap: 12,
      nameTextStyle: { fontSize: 12, color: '#1f2937', fontWeight: 600 },
      // 整数模式强制刻度间隔 ≥ 1（避免 ECharts 自动算 0.5 间隔）
      minInterval: props.valueType === 'integer' ? 1 : undefined,
      axisLabel: {
        fontSize: 11,
        formatter: (val: number) => {
          const abs = Math.abs(val)
          // 整数模式（计数）：超过 6 位数用万/亿简写
          if (props.valueType === 'integer') {
            if (abs >= 1e8) return `${(val / 1e8).toFixed(1)}亿`
            if (abs >= 1e4) return `${(val / 1e4).toFixed(1)}万`
            return val.toLocaleString()  // 整数 + 千位分隔符
          }
          // 小数模式（默认）：6 位数以上才简写
          if (abs >= 1e12) return `${(val / 1e12).toFixed(1)}T`
          if (abs >= 1e9) return `${(val / 1e9).toFixed(1)}G`
          if (abs >= 1e6) return `${(val / 1e6).toFixed(1)}M`
          if (abs >= 1e3) return val.toLocaleString()  // 千位分隔符：1,234
          if (abs >= 1) return val.toFixed(0)
          return val.toFixed(2)
        },
      },
    },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', start: 0, end: 100, height: 20, bottom: 0 },
    ],
    grid: { top: 60, right: 60, bottom: 50, left: 70 },
    series: props.series.map(s => ({
      name: s.name,
      type: 'line',
      data: s.data,
      showSymbol: false,
      smooth: true,
      lineStyle: { width: 1.5 },
    })),
  }
}

function initChart() {
  if (!chartRef.value) return
  if (chartInstance) chartInstance.dispose()
  chartInstance = echarts.init(chartRef.value)
  chartInstance.setOption(buildOptions())
  // 点击图表上的点 → 把 timestamp 回传给父组件（用于"选时间点"）
  if (props.onPointClick) {
    chartInstance.on('click', (params: any) => {
      // params.value 是 [ts, val] 二元组
      if (params && params.value && Array.isArray(params.value) && params.value.length >= 1) {
        const ts = String(params.value[0])
        if (ts) props.onPointClick!(ts)
      }
    })
  }
}

onMounted(initChart)

watch(() => [props.series, props.title, props.onPointClick], initChart, { deep: true })

window.addEventListener('resize', () => chartInstance?.resize())
</script>

<template>
  <div ref="chartRef" class="timeline-chart" :style="{ height: (props.height || 300) + 'px' }" />
</template>

<style scoped>
.timeline-chart {
  width: 100%;
  background: white;
  border-radius: 8px;
  padding: 6px;
}
</style>
