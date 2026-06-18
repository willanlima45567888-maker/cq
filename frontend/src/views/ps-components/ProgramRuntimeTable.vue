<script setup lang="ts">
/**
 * 程序运行时长统计表
 *
 * 替代原来的生命周期甘特图，按运行时长降序展示所有"重要"进程。
 * 顶部 4 张汇总卡片：
 *   - 跟踪进程数
 *   - 全周期都在（runtime = 总时长，frequency 100%）
 *   - ≥80% 周期
 *   - 只出现 1 个 cycle（一次性进程）
 */
import { computed, ref } from 'vue'
import type { PsLifecycleEntry } from '../../api/ps'

const props = defineProps<{
  lifecycle: PsLifecycleEntry[]
  /** 总 cycle 数（用于显示 X / N） */
  totalCycles: number
}>()

const CAT_LABELS: Record<string, string> = {
  oracle: 'Oracle',
  grid: 'Grid',
  system: 'System',
  script: 'Script',
}

type SortKey = 'duration' | 'name' | 'pid_count' | 'cycles_seen' | 'frequency'
const sortKey = ref<SortKey>('duration')
const sortDesc = ref(true)
const categoryFilter = ref<string>('all')
const showLimit = ref(100)

const sorted = computed(() => {
  let arr = props.lifecycle
  if (categoryFilter.value !== 'all') {
    arr = arr.filter((l) => l.category === categoryFilter.value)
  }
  const k = sortKey.value
  const desc = sortDesc.value
  return [...arr].sort((a, b) => {
    let va: number | string
    let vb: number | string
    if (k === 'name') {
      va = a.name
      vb = b.name
    } else if (k === 'duration') {
      va = a.duration_seconds
      vb = b.duration_seconds
    } else if (k === 'pid_count') {
      va = a.pid_count
      vb = b.pid_count
    } else if (k === 'cycles_seen') {
      va = a.cycles_seen
      vb = b.cycles_seen
    } else {  // frequency
      va = a.frequency_pct
      vb = b.frequency_pct
    }
    if (typeof va === 'number' && typeof vb === 'number') {
      return desc ? vb - va : va - vb
    }
    return desc
      ? String(vb).localeCompare(String(va))
      : String(va).localeCompare(String(vb))
  })
})

const displayed = computed(() => sorted.value.slice(0, showLimit.value))
const hiddenCount = computed(() => Math.max(0, sorted.value.length - showLimit.value))

function setSort(k: SortKey) {
  if (sortKey.value === k) {
    sortDesc.value = !sortDesc.value
  } else {
    sortKey.value = k
    sortDesc.value = true
  }
}

// 汇总
const summary = computed(() => {
  const total = props.lifecycle.length
  const alive_all = props.lifecycle.filter((l) => l.cycles_seen === props.totalCycles).length
  const alive_most = props.lifecycle.filter((l) => l.frequency_pct >= 80).length
  const one_off = props.lifecycle.filter((l) => l.cycles_seen === 1).length
  // 各类别数量
  const byCat: Record<string, number> = { oracle: 0, grid: 0, system: 0, script: 0 }
  for (const l of props.lifecycle) {
    byCat[l.category] = (byCat[l.category] ?? 0) + 1
  }
  return { total, alive_all, alive_most, one_off, byCat }
})

function fmtDuration(sec: number): string {
  if (!sec || sec < 0) return '0s'
  if (sec < 60) return `${sec.toFixed(0)}s`
  if (sec < 3600) {
    const m = Math.floor(sec / 60)
    const s = Math.floor(sec % 60)
    return s > 0 ? `${m}m ${s}s` : `${m}m`
  }
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

function shortTs(ts: string): string {
  if (!ts) return ''
  const m = ts.match(/^\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/)
  if (m) return `${m[1]}-${m[2]} ${m[3]}:${m[4]}:${m[5]}`
  return ts
}

function shortName(name: string, max = 55): string {
  if (name.length <= max) return name
  return name.slice(0, max) + '...'
}
</script>

<template>
  <div class="runtime-table">
    <!-- 汇总卡片 -->
    <div class="summary-grid">
      <div class="summary-card">
        <div class="summary-label">跟踪进程数</div>
        <div class="summary-value">{{ summary.total }}</div>
        <div class="summary-sub">
          Oracle {{ summary.byCat.oracle ?? 0 }} ·
          Grid {{ summary.byCat.grid ?? 0 }} ·
          Script {{ summary.byCat.script ?? 0 }} ·
          System {{ summary.byCat.system ?? 0 }}
        </div>
      </div>
      <div class="summary-card summary-full">
        <div class="summary-label">全周期都在</div>
        <div class="summary-value">{{ summary.alive_all }}</div>
        <div class="summary-sub">frequency = 100% 的进程</div>
      </div>
      <div class="summary-card summary-most">
        <div class="summary-label">≥80% 周期</div>
        <div class="summary-value">{{ summary.alive_most }}</div>
        <div class="summary-sub">长时间活跃</div>
      </div>
      <div class="summary-card summary-once">
        <div class="summary-label">只出现 1 cycle</div>
        <div class="summary-value">{{ summary.one_off }}</div>
        <div class="summary-sub">一次性 / 极短任务</div>
      </div>
    </div>

    <!-- 过滤器 + 显示上限 -->
    <div class="filter-row">
      <label>类别：</label>
      <select v-model="categoryFilter">
        <option value="all">全部（{{ summary.total }}）</option>
        <option value="oracle">Oracle（{{ summary.byCat.oracle ?? 0 }}）</option>
        <option value="grid">Grid（{{ summary.byCat.grid ?? 0 }}）</option>
        <option value="script">Script（{{ summary.byCat.script ?? 0 }}）</option>
        <option value="system">System（{{ summary.byCat.system ?? 0 }}）</option>
      </select>
      <label>显示：</label>
      <select v-model.number="showLimit">
        <option :value="50">前 50 条</option>
        <option :value="100">前 100 条</option>
        <option :value="200">前 200 条</option>
        <option :value="500">前 500 条</option>
        <option :value="99999">全部</option>
      </select>
      <span class="hint">点击列头排序</span>
    </div>

    <!-- 表格 -->
    <table class="rt-table">
      <thead>
        <tr>
          <th @click="setSort('name')" :class="{ active: sortKey === 'name' }">程序</th>
          <th>类别</th>
          <th @click="setSort('pid_count')" :class="{ active: sortKey === 'pid_count' }">PID 数</th>
          <th>首次出现</th>
          <th>最后出现</th>
          <th @click="setSort('duration')" :class="{ active: sortKey === 'duration' }">运行时长</th>
          <th @click="setSort('cycles_seen')" :class="{ active: sortKey === 'cycles_seen' }">出现 cycle</th>
          <th @click="setSort('frequency')" :class="{ active: sortKey === 'frequency' }">频率</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="l in displayed" :key="`${l.category}-${l.name}`">
          <td><code class="cmd-cell" :title="l.name">{{ shortName(l.name, 55) }}</code></td>
          <td><code :class="`cat-tag cat-${l.category}`">{{ CAT_LABELS[l.category] }}</code></td>
          <td :class="{ high: l.pid_count > 1 }">{{ l.pid_count }}</td>
          <td class="ts-cell">{{ shortTs(l.first_seen) }}</td>
          <td class="ts-cell">{{ shortTs(l.last_seen) }}</td>
          <td class="dur-cell" :class="{ full: l.frequency_pct >= 99 }">{{ fmtDuration(l.duration_seconds) }}</td>
          <td>{{ l.cycles_seen }} / {{ totalCycles }}</td>
          <td>
            <div class="freq-bar-wrap">
              <div class="freq-bar" :style="{ width: `${Math.min(l.frequency_pct, 100)}%` }"></div>
              <span class="freq-num">{{ l.frequency_pct.toFixed(1) }}%</span>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-if="hiddenCount > 0" class="more-hint">
      还有 {{ hiddenCount }} 条未显示，调整"显示"或过滤条件查看
    </div>
  </div>
</template>

<style scoped>
.runtime-table {
  width: 100%;
}

/* ─── 汇总卡片 ─── */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}
.summary-card {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px 16px;
}
.summary-card.summary-full { background: #f0fdf4; border-color: #bbf7d0; }
.summary-card.summary-most { background: #eff6ff; border-color: #bfdbfe; }
.summary-card.summary-once { background: #fef3c7; border-color: #fde68a; }
.summary-label {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 4px;
}
.summary-value {
  font-size: 26px;
  font-weight: 700;
  color: #1f2937;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
.summary-sub {
  font-size: 11px;
  color: #9ca3af;
  margin-top: 2px;
}

/* ─── 过滤行 ─── */
.filter-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
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

/* ─── 表格 ─── */
.rt-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  overflow: hidden;
  table-layout: fixed;
}
.rt-table th,
.rt-table td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid #f3f4f6;
  overflow: hidden;
  text-overflow: ellipsis;
}
.rt-table th {
  color: #6b7280;
  font-weight: 600;
  background: #f9fafb;
  font-size: 12px;
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}
.rt-table th:hover { background: #f3f4f6; }
.rt-table th.active { color: #2563eb; background: #eff6ff; }
.rt-table tbody tr:last-child td { border-bottom: none; }
.rt-table .high { color: #dc2626; font-weight: 600; }
.rt-table .ts-cell { font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 11px; color: #4b5563; }
.rt-table .dur-cell { font-family: 'SF Mono', Menlo, Consolas, monospace; font-weight: 500; color: #1f2937; }
.rt-table .dur-cell.full { color: #15803d; font-weight: 700; }

.cmd-cell {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  color: #374151;
  word-break: break-all;
}

.cat-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 10px;
  font-weight: 600;
  white-space: nowrap;
}
.cat-oracle { background: #fef2f2; color: #b91c1c; }
.cat-grid { background: #f0fdf4; color: #15803d; }
.cat-script { background: #faf5ff; color: #6d28d9; }
.cat-system { background: #f3f4f6; color: #374151; }

/* 频率进度条 */
.freq-bar-wrap {
  position: relative;
  width: 100%;
  height: 18px;
  background: #f3f4f6;
  border-radius: 9px;
  overflow: hidden;
}
.freq-bar {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: linear-gradient(90deg, #93c5fd, #2563eb);
  border-radius: 9px 0 0 9px;
  transition: width 0.3s;
}
.freq-num {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 600;
  color: #1f2937;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  z-index: 1;
  mix-blend-mode: difference;
  filter: invert(1);
}

.more-hint {
  margin-top: 8px;
  padding: 6px 10px;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  border-radius: 4px;
  font-size: 12px;
  color: #9a3412;
  text-align: center;
}
</style>
