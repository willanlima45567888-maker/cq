<script setup lang="ts">
import { computed } from 'vue'
import type { ParseResponse } from '../api/osw'

const props = defineProps<{
  data: ParseResponse | null
  selectedDevices: string[]
}>()

type StatKey = 'min' | 'max' | 'avg' | 'sum' | 'p50' | 'p95' | 'std'

interface StatEntry {
  device: string
  metric: string
  min: number
  max: number
  avg: number
  sum: number
  p50: number
  p95: number
  std: number
}

function percentile(sortedArr: number[], p: number): number {
  if (!sortedArr.length) return 0
  const idx = Math.ceil((p / 100) * sortedArr.length) - 1
  return sortedArr[Math.max(0, Math.min(idx, sortedArr.length - 1))]
}

function stdDev(arr: number[], mean: number): number {
  if (arr.length < 2) return 0
  const squareDiffs = arr.map(v => Math.pow(v - mean, 2))
  return Math.sqrt(squareDiffs.reduce((a, b) => a + b, 0) / arr.length)
}

const tableData = computed<StatEntry[]>(() => {
  if (!props.data) return []

  const cycles = props.data.data.cycles
  const selected = props.selectedDevices
  const metrics = props.data.metrics

  const result: StatEntry[] = []

  for (const devName of selected) {
    for (const metric of metrics) {
      const values: number[] = []
      for (const cyc of cycles) {
        const dev = cyc.devices.find((d: any) => d.device === devName)
        if (dev && metric in dev && dev[metric] !== null && dev[metric] !== undefined) {
          values.push(dev[metric] as number)
        }
      }
      if (!values.length) continue

      const sorted = [...values].sort((a, b) => a - b)
      const sum = values.reduce((a, b) => a + b, 0)
      const avg = sum / values.length

      result.push({
        device: devName,
        metric,
        min: sorted[0],
        max: sorted[sorted.length - 1],
        avg: parseFloat(avg.toFixed(3)),
        sum: parseFloat(sum.toFixed(3)),
        p50: parseFloat(percentile(sorted, 50).toFixed(3)),
        p95: parseFloat(percentile(sorted, 95).toFixed(3)),
        std: parseFloat(stdDev(values, avg).toFixed(3)),
      })
    }
  }

  return result
})
</script>

<template>
  <div class="stats-overview">
    <h3>统计概览</h3>
    <div class="table-wrapper">
      <table v-if="tableData.length">
        <thead>
          <tr>
            <th>设备</th>
            <th>指标</th>
            <th>min</th>
            <th>max</th>
            <th>avg</th>
            <th>sum</th>
            <th>P50</th>
            <th>P95</th>
            <th>std</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in tableData" :key="`${row.device}-${row.metric}`">
            <td class="device">{{ row.device }}</td>
            <td>{{ row.metric }}</td>
            <td>{{ row.min }}</td>
            <td>{{ row.max }}</td>
            <td>{{ row.avg }}</td>
            <td>{{ row.sum }}</td>
            <td>{{ row.p50 }}</td>
            <td>{{ row.p95 }}</td>
            <td>{{ row.std }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">无数据</div>
    </div>
  </div>
</template>

<style scoped>
.stats-overview {
  background: white;
  border-radius: 8px;
  padding: 16px;
}
h3 {
  margin-bottom: 12px;
  font-size: 15px;
  color: #333;
}
.table-wrapper {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th, td {
  padding: 6px 10px;
  text-align: right;
  border-bottom: 1px solid #eee;
  white-space: nowrap;
}
th {
  background: #f5f5f5;
  font-weight: 600;
  color: #555;
  position: sticky;
  top: 0;
}
td.device {
  font-family: monospace;
  color: #666;
}
tr:hover td {
  background: #fafafa;
}
.empty {
  text-align: center;
  color: #999;
  padding: 32px;
}
</style>
