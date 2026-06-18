<script setup lang="ts">
/**
 * CPU TOP N 柱状图（横向）
 */
import { onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { PsCpuTopEntry } from '../../api/ps'

const props = defineProps<{
  entries: PsCpuTopEntry[]
  /** 显示条数，默认全部 */
  topN?: number
}>()

const chartRef = ref<HTMLDivElement | null>(null)
let chartInstance: echarts.ECharts | null = null

function shortCmd(cmd: string, max = 50): string {
  if (cmd.length <= max) return cmd
  return cmd.slice(0, max) + '...'
}

/** 取命令行"程序名"用于 y 轴紧凑显示（与 analyzer._cmd_basename 同思路） */
function cmdBasename(cmd: string): string {
  if (!cmd) return ''
  const parts = cmd.split()
  const first = parts[0]
  // shell 解释器链：/bin/sh ./backup.sh → backup.sh
  if (['/bin/sh', '/bin/bash', '/bin/dash', '/usr/bin/env'].includes(first) && parts.length >= 2) {
    return parts[1].split('/').filter(Boolean).pop() || parts[1]
  }
  let base = first.split('/').filter(Boolean).pop() || first
  // "sshd: sendoh@notty" → sshd
  if (base.includes(':')) base = base.split(':', 1)[0]
  return base
}

/** 时间戳截到分钟（HH:MM）用于 tooltip 紧凑显示 */
function shortTs(ts: string): string {
  if (!ts) return ''
  // ISO 形式 "2026-06-07T01:00:03" → "06-07 01:00"
  const m = ts.match(/^\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  if (m) return `${m[1]}-${m[2]} ${m[3]}:${m[4]}`
  return ts
}

function buildOptions() {
  const n = props.topN ?? props.entries.length
  const data = props.entries.slice(0, n).slice().reverse()  // ECharts 横向柱状从下往上 → reverse
  return {
    tooltip: {
      trigger: 'item' as const,
      confine: true,  // 关键：tooltip 不超出图表区域
      extraCssText: 'max-width: 360px; white-space: normal; word-break: break-all;',
      formatter: (p: any) => {
        const e = data[p.dataIndex]
        return `<div style="font-family: SF Mono, Menlo, monospace; font-size: 12px;">` +
          `<strong>${e.user}</strong> · <code>${cmdBasename(e.command)}</code> · PID ${e.pid}<br/>` +
          `<span style="color:#9ca3af">${shortCmd(e.command, 80)}</span><br/>` +
          `<span style="color:#dc2626">最大 ${e.cpu_pct_max.toFixed(1)}%</span> · 平均 ${e.cpu_pct_avg.toFixed(1)}% · ${e.cycles_seen} 次<br/>` +
          `<span style="color:#6b7280">${shortTs(e.first_seen)} → ${shortTs(e.last_seen)}</span>` +
          `</div>`
      },
    },
    grid: { top: 10, right: 60, bottom: 10, left: 200 },
    xAxis: { type: 'value' as const, name: '%', axisLabel: { fontSize: 11 } },
    yAxis: {
      type: 'category' as const,
      data: data.map((e) => `${e.user} · ${cmdBasename(e.command)}`),
      axisLabel: {
        fontSize: 11,
        fontFamily: 'SF Mono, Menlo, Consolas, monospace',
        color: '#374151',
        formatter: (val: string) => {
          // 超过 28 字符截断
          if (val.length <= 28) return val
          return val.slice(0, 28) + '…'
        },
      },
    },
    series: [
      {
        type: 'bar' as const,
        data: data.map((e) => e.cpu_pct_max),
        itemStyle: {
          color: (params: any) => {
            const v = params.value
            if (v >= 100) return '#dc2626'
            if (v >= 50) return '#ea580c'
            if (v >= 20) return '#d97706'
            return '#2563eb'
          },
        },
        label: {
          show: true,
          position: 'right' as const,
          formatter: '{c}%',
          fontSize: 10,
        },
      },
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
watch(() => props.entries, initChart, { deep: true })
window.addEventListener('resize', () => chartInstance?.resize())
</script>

<template>
  <div ref="chartRef" class="chart" />
</template>

<style scoped>
.chart {
  width: 100%;
  height: 600px;
  background: white;
  border-radius: 8px;
  padding: 8px;
}
</style>
