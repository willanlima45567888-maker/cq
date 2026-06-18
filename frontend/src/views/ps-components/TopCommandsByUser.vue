<script setup lang="ts">
/**
 * TOP 进程按用户分组（显示具体命令，不是 basename）
 *
 * 与 CpuTopBar / MemoryTopBar 的关系：
 *   - Bar chart 用 basename 紧凑显示
 *   - 本组件用具体命令（完整路径/参数），按用户分组展开
 *     适合需要识别"具体哪条 OPatch 任务"或"哪个具体 java 进程"的场景
 */
import { computed } from 'vue'
import type { PsCpuTopEntry, PsMemTopEntry } from '../../api/ps'

interface Props {
  cpuEntries: PsCpuTopEntry[]
  memEntries: PsMemTopEntry[]
  /** 每用户最多显示多少条（按 value 降序） */
  perUserLimit?: number
}

const props = withDefaults(defineProps<Props>(), {
  perUserLimit: 5,
})

type Tab = 'cpu' | 'mem'
const activeTab = ref<Tab>('cpu')

interface UserGroup {
  user: string
  cpuEntries: PsCpuTopEntry[]
  memEntries: PsMemTopEntry[]
  cpuMax: number
  memMaxKb: number
}

const groups = computed<UserGroup[]>(() => {
  // 按用户分组
  const byUser = new Map<string, { cpu: PsCpuTopEntry[]; mem: PsMemTopEntry[] }>()
  for (const c of props.cpuEntries) {
    if (!byUser.has(c.user)) byUser.set(c.user, { cpu: [], mem: [] })
    byUser.get(c.user)!.cpu.push(c)
  }
  for (const m of props.memEntries) {
    if (!byUser.has(m.user)) byUser.set(m.user, { cpu: [], mem: [] })
    byUser.get(m.user)!.mem.push(m)
  }
  // 排序：每组按值降序截断
  const result: UserGroup[] = []
  for (const [user, { cpu, mem }] of byUser) {
    cpu.sort((a, b) => b.cpu_pct_max - a.cpu_pct_max)
    mem.sort((a, b) => b.rss_max_kb - a.rss_max_kb)
    result.push({
      user,
      cpuEntries: cpu.slice(0, props.perUserLimit),
      memEntries: mem.slice(0, props.perUserLimit),
      cpuMax: cpu.length > 0 ? cpu[0].cpu_pct_max : 0,
      memMaxKb: mem.length > 0 ? mem[0].rss_max_kb : 0,
    })
  }
  // 排序：按 CPU TOP 1 最大者降序（高占用用户在前）
  result.sort((a, b) => b.cpuMax - a.cpuMax)
  return result
})

function shortCmd(cmd: string, max = 80): string {
  if (!cmd) return ''
  if (cmd.length <= max) return cmd
  return cmd.slice(0, max) + '...'
}

function formatKB(kb: number): string {
  if (kb >= 1024 * 1024) return `${(kb / 1024 / 1024).toFixed(2)} G`
  if (kb >= 1024) return `${(kb / 1024).toFixed(1)} M`
  return `${Math.round(kb)} K`
}

import { ref } from 'vue'
</script>

<template>
  <div class="top-by-user">
    <!-- Tab 切换 -->
    <div class="tabs">
      <button
        class="tab"
        :class="{ active: activeTab === 'cpu' }"
        @click="activeTab = 'cpu'"
      >
        CPU TOP（按用户分组 · 具体命令）
      </button>
      <button
        class="tab"
        :class="{ active: activeTab === 'mem' }"
        @click="activeTab = 'mem'"
      >
        Memory TOP（按用户分组 · 具体命令）
      </button>
    </div>

    <div v-if="groups.length === 0" class="empty">无数据</div>

    <!-- CPU 视图 -->
    <div v-else-if="activeTab === 'cpu'">
      <div v-for="g in groups" :key="`cpu-${g.user}`" class="user-block">
        <div class="user-header">
          <code class="user-tag">{{ g.user }}</code>
          <span class="user-meta">
            TOP {{ Math.min(g.cpuEntries.length, perUserLimit) }}（共 {{ g.cpuEntries.length }} 条）
            · 最高 {{ g.cpuMax.toFixed(1) }}%
          </span>
        </div>
        <table class="cmd-table">
          <thead>
            <tr>
              <th>PID</th>
              <th>CPU% max</th>
              <th>CPU% avg</th>
              <th>出现 cycle</th>
              <th>具体命令</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in g.cpuEntries" :key="c.pid">
              <td>{{ c.pid }}</td>
              <td :class="{ high: c.cpu_pct_max >= 50, very_high: c.cpu_pct_max >= 100 }">
                {{ c.cpu_pct_max.toFixed(1) }}%
              </td>
              <td>{{ c.cpu_pct_avg.toFixed(1) }}%</td>
              <td>{{ c.cycles_seen }}</td>
              <td><code class="cmd-cell" :title="c.command">{{ shortCmd(c.command, 100) }}</code></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Memory 视图 -->
    <div v-else>
      <div v-for="g in groups" :key="`mem-${g.user}`" class="user-block">
        <div class="user-header">
          <code class="user-tag">{{ g.user }}</code>
          <span class="user-meta">
            TOP {{ Math.min(g.memEntries.length, perUserLimit) }}（共 {{ g.memEntries.length }} 条）
            · 最高 {{ formatKB(g.memMaxKb) }}
          </span>
        </div>
        <table class="cmd-table">
          <thead>
            <tr>
              <th>PID</th>
              <th>RSS max</th>
              <th>RSS avg</th>
              <th>VSZ max</th>
              <th>出现 cycle</th>
              <th>具体命令</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in g.memEntries" :key="m.pid">
              <td>{{ m.pid }}</td>
              <td :class="{ high: m.rss_max_kb >= 1024 * 1024, very_high: m.rss_max_kb >= 2 * 1024 * 1024 }">
                {{ formatKB(m.rss_max_kb) }}
              </td>
              <td>{{ formatKB(m.rss_avg_kb) }}</td>
              <td>{{ formatKB(m.vsz_max_kb) }}</td>
              <td>{{ m.cycles_seen }}</td>
              <td><code class="cmd-cell" :title="m.command">{{ shortCmd(m.command, 100) }}</code></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.top-by-user {
  width: 100%;
}

.tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid #e5e7eb;
  margin-bottom: 14px;
}
.tab {
  padding: 6px 14px;
  background: transparent;
  border: none;
  font-size: 13px;
  color: #6b7280;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}
.tab:hover { color: #374151; }
.tab.active {
  color: #2563eb;
  border-bottom-color: #2563eb;
  font-weight: 600;
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

.user-block {
  margin-bottom: 18px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  overflow: hidden;
}
.user-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: #f9fafb;
  border-bottom: 1px solid #e5e7eb;
}
.user-tag {
  background: #eff6ff;
  color: #1e3a8a;
  padding: 2px 10px;
  border-radius: 4px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 12px;
  font-weight: 600;
}
.user-meta {
  font-size: 12px;
  color: #6b7280;
}

.cmd-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.cmd-table th,
.cmd-table td {
  text-align: left;
  padding: 5px 10px;
  border-bottom: 1px solid #f3f4f6;
  vertical-align: top;
}
.cmd-table th {
  color: #6b7280;
  font-weight: 600;
  background: #fafafa;
  font-size: 11px;
  white-space: nowrap;
}
.cmd-table tbody tr:last-child td { border-bottom: none; }
.cmd-table .high { color: #ea580c; font-weight: 600; }
.cmd-table .very_high { color: #dc2626; font-weight: 700; }
.cmd-cell {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  color: #374151;
  word-break: break-all;
  line-height: 1.4;
}
</style>
