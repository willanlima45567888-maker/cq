<script setup lang="ts">
/**
 * PsProcessTable — ps 工具专用：单个 cycle 的进程表
 *
 * 设计：显示 USER / PID / %CPU / %MEM / RSS / STARTED / TIME / COMMAND
 *  - 可按 USER / %CPU / %MEM / RSS 排序
 *  - 进程很多时只显示前 N 行（默认 200），下方提示"还有 N 行未显示"
 */

import { computed, ref } from 'vue'
import type { PsCycle } from '../../api/ps'

const props = defineProps<{
  cycle: PsCycle
  /** 最多显示多少行（防止几万个进程打爆 DOM） */
  maxRows?: number
}>()

type SortKey = 'user' | 'pid' | 'cpu_pct' | 'mem_pct' | 'rss' | 'started'
const sortKey = ref<SortKey>('cpu_pct')
const sortDesc = ref(true)

const maxRows = computed(() => props.maxRows ?? 200)

const sorted = computed(() => {
  const arr = [...props.cycle.processes]
  const k = sortKey.value
  arr.sort((a, b) => {
    const va = a[k] as number | string
    const vb = b[k] as number | string
    if (typeof va === 'number' && typeof vb === 'number') {
      return sortDesc.value ? vb - va : va - vb
    }
    return sortDesc.value
      ? String(vb).localeCompare(String(va))
      : String(va).localeCompare(String(vb))
  })
  return arr
})

const displayed = computed(() => sorted.value.slice(0, maxRows.value))
const hiddenCount = computed(() => Math.max(0, sorted.value.length - maxRows.value))

function setSort(k: SortKey) {
  if (sortKey.value === k) {
    sortDesc.value = !sortDesc.value
  } else {
    sortKey.value = k
    sortDesc.value = true
  }
}

function fmtBytes(kb: number): string {
  if (kb < 1024) return `${kb} K`
  if (kb < 1024 * 1024) return `${(kb / 1024).toFixed(1)} M`
  return `${(kb / 1024 / 1024).toFixed(2)} G`
}
</script>

<template>
  <div class="proc-table">
    <div class="meta">
      <span class="ts">{{ cycle.timestamp }}</span>
      <span class="count">{{ cycle.processes.length }} 个进程</span>
      <span v-if="hiddenCount > 0" class="hidden-hint">（仅显示前 {{ maxRows }} 行）</span>
    </div>
    <table>
      <thead>
        <tr>
          <th @click="setSort('user')" :class="{ active: sortKey === 'user' }">USER</th>
          <th @click="setSort('pid')" :class="{ active: sortKey === 'pid' }">PID</th>
          <th @click="setSort('cpu_pct')" :class="{ active: sortKey === 'cpu_pct' }">%CPU</th>
          <th @click="setSort('mem_pct')" :class="{ active: sortKey === 'mem_pct' }">%MEM</th>
          <th @click="setSort('rss')" :class="{ active: sortKey === 'rss' }">RSS</th>
          <th @click="setSort('started')" :class="{ active: sortKey === 'started' }">STARTED</th>
          <th>TIME</th>
          <th>COMMAND</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="p in displayed" :key="`${p.pid}-${p.command}`">
          <td><code class="user">{{ p.user }}</code></td>
          <td>{{ p.pid }}</td>
          <td :class="{ high: p.cpu_pct >= 10 }">{{ p.cpu_pct.toFixed(1) }}</td>
          <td :class="{ high: p.mem_pct >= 5 }">{{ p.mem_pct.toFixed(1) }}</td>
          <td>{{ fmtBytes(p.rss) }}</td>
          <td>{{ p.started }}</td>
          <td>{{ p.time }}</td>
          <td><code class="cmd">{{ p.command }}</code></td>
        </tr>
      </tbody>
    </table>
    <div v-if="hiddenCount > 0" class="more">
      还有 {{ hiddenCount }} 行未显示（按列头排序或调整 maxRows 切换显示）
    </div>
  </div>
</template>

<style scoped>
.proc-table {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 16px;
}
.meta {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 13px;
}
.meta .ts {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  color: #1e3a8a;
  font-weight: 500;
}
.meta .count {
  color: #555;
}
.meta .hidden-hint {
  color: #9a3412;
  font-size: 12px;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
th, td {
  text-align: left;
  padding: 4px 8px;
  border-bottom: 1px solid #f3f4f6;
}
th {
  color: #6b7280;
  font-weight: 600;
  cursor: pointer;
  user-select: none;
  background: #f9fafb;
  position: sticky;
  top: 0;
}
th:hover {
  background: #f3f4f6;
}
th.active {
  color: #2563eb;
  background: #eff6ff;
}
td.high {
  color: #dc2626;
  font-weight: 600;
}
code.user {
  background: #f0f4ff;
  color: #1e3a8a;
  padding: 0 6px;
  border-radius: 3px;
  font-size: 11px;
}
code.cmd {
  color: #374151;
  word-break: break-all;
  font-size: 11px;
}
.more {
  margin-top: 8px;
  padding: 6px 10px;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  border-radius: 4px;
  font-size: 12px;
  color: #9a3412;
}
</style>
