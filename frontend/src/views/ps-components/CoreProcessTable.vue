<script setup lang="ts">
/**
 * 核心 8 字段进程表
 *
 * 来源：cpu_top ∪ mem_top（已 enrich，含 RSS/STATE/WCHAN/STARTED）
 * 列：USER | PID | %CPU max | RSS max | STATE | WCHAN | STARTED | COMMAND
 *
 * - 默认按 %CPU 降序
 * - 可按任意列点击排序
 * - 可按 USER / STATE 过滤
 */
import { computed, ref } from 'vue'
import type { PsCpuTopEntry, PsMemTopEntry } from '../../api/ps'

// 合并 cpu_top + mem_top（按 pid 去重，ps 数据可能两者重叠）
type CoreEntry = PsCpuTopEntry & { sort_cpu: number; sort_rss: number }

const props = defineProps<{
  cpuEntries: PsCpuTopEntry[]
  memEntries: PsMemTopEntry[]
}>()

const merged = computed<CoreEntry[]>(() => {
  const map = new Map<number, CoreEntry>()
  for (const c of props.cpuEntries) {
    map.set(c.pid, { ...c, sort_cpu: c.cpu_pct_max, sort_rss: c.rss_max_kb })
  }
  for (const m of props.memEntries) {
    const existing = map.get(m.pid)
    if (existing) {
      // 已存在（来自 cpu_top），合并 mem 数据
      existing.sort_rss = Math.max(existing.sort_rss, m.rss_max_kb)
      // 保留 cpu_top 的 cpu 数据
    } else {
      map.set(m.pid, {
        ...m,
        cpu_pct_max: m.cpu_pct_max ?? 0,
        cpu_pct_avg: m.cpu_pct_avg ?? 0,
        sort_cpu: m.cpu_pct_max ?? 0,
        sort_rss: m.rss_max_kb,
      })
    }
  }
  return Array.from(map.values())
})

// 过滤
const userFilter = ref<string>('all')
const stateFilter = ref<string>('all')
const pidFilter = ref<string>('')
const filteredEntries = computed(() => {
  return merged.value.filter((e) => {
    if (userFilter.value !== 'all' && e.user !== userFilter.value) return false
    if (stateFilter.value !== 'all' && e.state !== stateFilter.value) return false
    if (pidFilter.value.trim()) {
      const q = pidFilter.value.trim()
      // 支持精确匹配 / 子串匹配
      if (!String(e.pid).includes(q)) return false
    }
    return true
  })
})

// 可用的 USER 和 STATE 选项
const userOptions = computed(() => {
  const set = new Set(merged.value.map((e) => e.user))
  return Array.from(set).sort()
})
const stateOptions = ['R', 'S', 'D', 'Z', 'T', 'I', 'X']

// 排序
type SortKey = 'sort_cpu' | 'sort_rss' | 'user' | 'pid' | 'state' | 'wchan' | 'started'
const sortKey = ref<SortKey>('sort_cpu')
const sortDesc = ref(true)

const sortedEntries = computed(() => {
  const arr = [...filteredEntries.value]
  const k = sortKey.value
  const desc = sortDesc.value
  arr.sort((a, b) => {
    let va: number | string = (a as any)[k]
    let vb: number | string = (b as any)[k]
    if (typeof va === 'number' && typeof vb === 'number') {
      return desc ? vb - va : va - vb
    }
    va = String(va ?? '')
    vb = String(vb ?? '')
    return desc ? vb.localeCompare(va) : va.localeCompare(vb)
  })
  return arr
})

function setSort(k: SortKey) {
  if (sortKey.value === k) {
    sortDesc.value = !sortDesc.value
  } else {
    sortKey.value = k
    sortDesc.value = true
  }
}

function shortCmd(cmd: string, max = 50): string {
  if (!cmd) return ''
  if (cmd.length <= max) return cmd
  return cmd.slice(0, max) + '...'
}

function formatKB(kb: number): string {
  if (kb >= 1024 * 1024) return `${(kb / 1024 / 1024).toFixed(2)} G`
  if (kb >= 1024) return `${(kb / 1024).toFixed(1)} M`
  return `${Math.round(kb)} K`
}

function shortTs(ts: string): string {
  if (!ts) return ''
  const m = ts.match(/^\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  if (m) return `${m[1]}-${m[2]} ${m[3]}:${m[4]}`
  return ts
}
</script>

<template>
  <div class="core-table">
    <!-- 过滤行 -->
    <div class="filter-row">
      <label>USER：</label>
      <select v-model="userFilter">
        <option value="all">全部（{{ merged.length }}）</option>
        <option v-for="u in userOptions" :key="u" :value="u">{{ u }}</option>
      </select>
      <label>STATE：</label>
      <select v-model="stateFilter">
        <option value="all">全部</option>
        <option v-for="s in stateOptions" :key="s" :value="s">{{ s }}</option>
      </select>
      <label>PID：</label>
      <input
        v-model="pidFilter"
        type="text"
        class="pid-input"
        placeholder="搜索 PID（子串）"
      />
      <button
        v-if="pidFilter.trim()"
        class="btn-mini"
        @click="pidFilter = ''"
        title="清空 PID 筛选"
      >×</button>
      <span class="hint">点击列头排序 · 显示 {{ sortedEntries.length }} 条</span>
    </div>

    <div v-if="sortedEntries.length === 0" class="empty">无匹配进程</div>

    <table v-else class="cp-table">
      <thead>
        <tr>
          <th @click="setSort('user')" :class="{ active: sortKey === 'user' }">USER</th>
          <th @click="setSort('pid')" :class="{ active: sortKey === 'pid' }">PID</th>
          <th @click="setSort('sort_cpu')" :class="{ active: sortKey === 'sort_cpu' }">%CPU max</th>
          <th @click="setSort('sort_rss')" :class="{ active: sortKey === 'sort_rss' }">RSS max</th>
          <th @click="setSort('state')" :class="{ active: sortKey === 'state' }">STATE</th>
          <th @click="setSort('wchan')" :class="{ active: sortKey === 'wchan' }">WCHAN</th>
          <th @click="setSort('started')" :class="{ active: sortKey === 'started' }">STARTED</th>
          <th>COMMAND</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="e in sortedEntries" :key="e.pid">
          <td><code class="user-tag">{{ e.user }}</code></td>
          <td>{{ e.pid }}</td>
          <td :class="{ high: e.cpu_pct_max >= 50, very_high: e.cpu_pct_max >= 100 }">
            {{ e.cpu_pct_max.toFixed(1) }}%
          </td>
          <td :class="{ high: e.rss_max_kb >= 1024 * 1024, very_high: e.rss_max_kb >= 2 * 1024 * 1024 }">
            {{ formatKB(e.rss_max_kb) }}
          </td>
          <td>
            <span
              class="state-tag"
              :class="`state-${e.state}`"
              :title="stateStateTitle(e.state)"
            >{{ e.state }}</span>
          </td>
          <td>
            <code class="wchan-cell" :title="e.wchan || '（R 状态 / 无等待）'">
              {{ e.wchan || '-' }}
            </code>
          </td>
          <td class="ts-cell">{{ shortTs(e.first_seen) }}</td>
          <td><code class="cmd-cell" :title="e.command">{{ shortCmd(e.command, 60) }}</code></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script lang="ts">
const STATE_TITLE: Record<string, string> = {
  R: 'Running - 正在 CPU 上运行',
  S: 'Sleeping - 可中断睡眠',
  D: 'Uninterruptible - IO 阻塞（重点关注）',
  Z: 'Zombie - 父进程未回收',
  T: 'Stopped - 被信号停止',
  I: 'Idle - 内核空闲线程',
  X: 'Dead',
}
export default {
  methods: {
    stateStateTitle(s: string) {
      return STATE_TITLE[s] ?? s
    },
  },
}
</script>

<style scoped>
.core-table {
  width: 100%;
}

.filter-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 13px;
  color: #374151;
  flex-wrap: wrap;
}
.filter-row select {
  padding: 4px 8px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  font-size: 13px;
  background: white;
}
.filter-row .hint {
  color: #9ca3af;
  font-size: 12px;
  margin-left: auto;
}

.empty {
  padding: 16px;
  background: #f9fafb;
  border: 1px dashed #d1d5db;
  border-radius: 6px;
  color: #6b7280;
  text-align: center;
  font-size: 13px;
}

.cp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  overflow: hidden;
  table-layout: auto;
}
.cp-table th,
.cp-table td {
  text-align: left;
  padding: 5px 8px;
  border-bottom: 1px solid #f3f4f6;
  vertical-align: top;
  white-space: nowrap;
}
.cp-table th {
  color: #6b7280;
  font-weight: 600;
  background: #f9fafb;
  font-size: 11px;
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}
.cp-table th:hover { background: #f3f4f6; }
.cp-table th.active { color: #2563eb; background: #eff6ff; }
.cp-table tbody tr:last-child td { border-bottom: none; }
.cp-table .high { color: #ea580c; font-weight: 600; }
.cp-table .very_high { color: #dc2626; font-weight: 700; }

.user-tag {
  background: #eff6ff;
  color: #1e3a8a;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
}
.state-tag {
  display: inline-block;
  width: 22px;
  text-align: center;
  padding: 1px 0;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  font-weight: 600;
  color: white;
}
.state-R { background: #dc2626; }
.state-S { background: #9ca3af; }
.state-D { background: #ea580c; }
.state-Z { background: #7c2d12; }
.state-T { background: #7c3aed; }
.state-I { background: #3b82f6; }
.state-X { background: #525252; }

.wchan-cell {
  background: #f3f4f6;
  color: #1f2937;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
}
.ts-cell {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 10px;
  color: #6b7280;
}
.cmd-cell {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  color: #374151;
  word-break: break-all;
  white-space: normal;
  max-width: 360px;
  display: inline-block;
}
</style>
