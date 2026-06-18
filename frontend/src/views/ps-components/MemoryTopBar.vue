<script setup lang="ts">
/**
 * Memory TOP N 柱状图（横向）
 */
import { onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { PsMemTopEntry } from '../../api/ps'

const props = defineProps<{
  entries: PsMemTopEntry[]
  topN?: number
}>()

const chartRef = ref<HTMLDivElement | null>(null)
let chartInstance: echarts.ECharts | null = null

function shortCmd(cmd: string, max = 50): string {
  if (cmd.length <= max) return cmd
  return cmd.slice(0, max) + '...'
}

function cmdBasename(cmd: string): string {
  if (!cmd) return ''
  const parts = cmd.split()
  const first = parts[0]
  if (['/bin/sh', '/bin/bash', '/bin/dash', '/usr/bin/env'].includes(first) && parts.length >= 2) {
    return parts[1].split('/').filter(Boolean).pop() || parts[1]
  }
  let base = first.split('/').filter(Boolean).pop() || first
  if (base.includes(':')) base = base.split(':', 1)[0]
  return base
}

function shortTs(ts: string): string {
  if (!ts) return ''
  const m = ts.match(/^\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  if (m) return `${m[1]}-${m[2]} ${m[3]}:${m[4]}`
  return ts
}

function formatKB(kb: number): string {
  if (kb >= 1024 * 1024) return `${(kb / 1024 / 1024).toFixed(2)} G`
  if (kb >= 1024) return `${(kb / 1024).toFixed(1)} M`
  return `${Math.round(kb)} K`
}

function buildOptions() {
  const n = props.topN ?? props.entries.length
  const data = props.entries.slice(0, n).slice().reverse()
  return {
    tooltip: {
      trigger: 'item' as const,
      confine: true,
      extraCssText: 'max-width: 360px; white-space: normal; word-break: break-all;',
      formatter: (p: any) => {
        const e = data[p.dataIndex]
        return `<div style="font-family: SF Mono, Menlo, monospace; font-size: 12px;">` +
          `<strong>${e.user}</strong> · <code>${cmdBasename(e.command)}</code> · PID ${e.pid}<br/>` +
          `<span style="color:#9ca3af">${shortCmd(e.command, 80)}</span><br/>` +
          `<span style="color:#dc2626">RSS 最大 ${formatKB(e.rss_max_kb)}</span> · 平均 ${formatKB(e.rss_avg_kb)} · ${e.cycles_seen} 次<br/>` +
          `<span style="color:#6b7280">VSZ ${formatKB(e.vsz_max_kb)}</span><br/>` +
          `<span style="color:#6b7280">${shortTs(e.first_seen)} → ${shortTs(e.last_seen)}</span>` +
          `</div>`
      },
    },
    grid: { top: 10, right: 70, bottom: 10, left: 200 },
    xAxis: { type: 'value' as const, name: 'RSS (KB)', axisLabel: { fontSize: 11 } },
    yAxis: {
      type: 'category' as const,
      data: data.map((e) => `${e.user} · ${cmdBasename(e.command)}`),
      axisLabel: {
        fontSize: 11,
        fontFamily: 'SF Mono, Menlo, Consolas, monospace',
        color: '#374151',
        formatter: (val: string) => {
          if (val.length <= 28) return val
          return val.slice(0, 28) + '…'
        },
      },
    },
    series: [
      {
        type: 'bar' as const,
        data: data.map((e) => e.rss_max_kb),
        itemStyle: {
          color: (params: any) => {
            const v = params.value
            if (v >= 2 * 1024 * 1024) return '#dc2626'  // ≥2G
            if (v >= 1024 * 1024) return '#ea580c'  // ≥1G
            if (v >= 512 * 1024) return '#d97706'  // ≥512M
            return '#2563eb'
          },
        },
        label: {
          show: true,
          position: 'right' as const,
          formatter: (p: any) => formatKB(p.value),
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
