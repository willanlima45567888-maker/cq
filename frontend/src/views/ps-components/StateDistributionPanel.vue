<script setup lang="ts">
/**
 * 进程状态分布组件
 *
 * 三部分：
 *   1. 状态含义说明（7 个状态 R/S/D/Z/T/I/X 的中文含义）
 *   2. 7 张状态卡片：当前数 / 周期峰值 / 全周期出现次数（带含义 tooltip）
 *   3. 异常进程表（持续 Z / 持续 D 列表）
 *
 * 注：原"堆叠面积图"已删除 — S/I 占 99.5%，把 D/Z/T 全部压成细线。
 *     改为更聚焦的 4 状态折线图（仅画 R/D/Z/T），S/I 不画。
 */
import { computed, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { PsStateAnalysis } from '../../api/ps'

const props = defineProps<{
  state: PsStateAnalysis
  totalCycles: number
}>()

// 状态完整含义（中文）
const STATE_DESC: Record<string, string> = {
  R: '正在 CPU 上运行',
  S: '可中断睡眠（等待事件/IO 完成，可被信号唤醒）',
  D: '不可中断睡眠（通常在内核 IO 等待，**无法 kill -9**）',
  Z: 'Zombie（已终止但父进程未 wait() 回收）',
  T: '被信号停止（SIGSTOP 等，fg 进程被 ^Z）',
  I: '内核空闲线程（空闲 CPU 时间片）',
  X: 'Dead（瞬间态，极少见）',
}

const chartRef = ref<HTMLDivElement | null>(null)
let chartInstance: echarts.ECharts | null = null

// 7 张卡片：颜色 + 图例名
const STATE_COLORS: Record<string, string> = {
  R: '#dc2626',  // 红
  S: '#9ca3af',  // 灰
  D: '#ea580c',  // 橙
  Z: '#7c2d12',  // 暗红
  T: '#7c3aed',  // 紫
  I: '#3b82f6',  // 蓝
  X: '#525252',  // 深灰
}

interface CardData {
  state: string
  legend: string
  current: number
  max: number    // 周期峰值（所有 cycle 中最大的那个）
  total: number  // 全周期累加（所有 cycle 该状态进程数求和）
  color: string
  isAbnormal: boolean
  desc: string
}

const cards = computed<CardData[]>(() => {
  return props.state.state_order.map((s) => {
    const cur = props.state.current[s] ?? 0
    const total = props.state.total_by_state[s] ?? 0
    let max = 0
    for (const row of props.state.by_cycle) {
      const v = row[s] ?? 0
      if (v > max) max = v
    }
    return {
      state: s,
      legend: props.state.state_legend[s] ?? '',
      current: cur,
      max,
      total,
      color: STATE_COLORS[s] ?? '#9ca3af',
      isAbnormal: s === 'Z' || s === 'D',
      desc: STATE_DESC[s] ?? '',
    }
  })
})

// 趋势图：只画 4 个"活跃"状态（R/D/Z/T）
const INTERESTING_STATES: readonly string[] = ['R', 'D', 'Z', 'T']

function buildOptions() {
  const tsArr = props.state.by_cycle.map((r) => r.timestamp)
  const series = INTERESTING_STATES.map((s) => ({
    name: `${s} (${props.state.state_legend[s]})`,
    type: 'line' as const,
    showSymbol: false,
    smooth: false,
    lineStyle: { width: 1.8, color: STATE_COLORS[s] },
    itemStyle: { color: STATE_COLORS[s] },
    data: tsArr.map((_ts, i) => props.state.by_cycle[i][s] ?? 0),
  }))
  return {
    tooltip: {
      trigger: 'axis' as const,
      axisPointer: { type: 'cross' as const },
      formatter: (params: any) => {
        if (!params.length) return ''
        let result = `<strong>${params[0].axisValue}</strong><br/>`
        for (const p of params) {
          if (p.value > 0) {
            result += `${p.marker} ${p.seriesName}: <strong>${p.value}</strong><br/>`
          }
        }
        return result
      },
    },
    legend: { top: 0, type: 'scroll' as const },
    xAxis: { type: 'time' as const, axisLabel: { fontSize: 11 } },
    yAxis: {
      type: 'value' as const,
      name: '进程数',
      axisLabel: { fontSize: 11 },
      minInterval: 1,  // Y 轴整数刻度
    },
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
watch(() => props.state, initChart, { deep: true })
window.addEventListener('resize', () => chartInstance?.resize())

function fmtNum(n: number): string {
  return n.toLocaleString()
}

function shortCmd(cmd: string, max = 50): string {
  if (!cmd) return ''
  if (cmd.length <= max) return cmd
  return cmd.slice(0, max) + '...'
}
</script>

<template>
  <div class="state-panel">
    <!-- 状态含义图例（放在最前，方便对照） -->
    <details class="state-legend-block" open>
      <summary>状态含义速查</summary>
      <table class="legend-table">
        <thead>
          <tr>
            <th>状态</th>
            <th>含义</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in props.state.state_order" :key="s">
            <td>
              <span class="state-code-inline" :style="{ background: STATE_COLORS[s] }">{{ s }}</span>
              <span class="state-legend-name">{{ props.state.state_legend[s] }}</span>
            </td>
            <td :class="{ abnormal: s === 'Z' || s === 'D' }">
              {{ STATE_DESC[s] }}
            </td>
          </tr>
        </tbody>
      </table>
    </details>

    <!-- 7 张状态卡片 -->
    <div class="state-cards">
      <div
        v-for="c in cards"
        :key="c.state"
        class="state-card"
        :class="{ 'state-card-abnormal': c.isAbnormal }"
        :style="{ borderColor: c.color }"
        :title="c.desc"
      >
        <div class="state-code" :style="{ background: c.color }">{{ c.state }}</div>
        <div class="state-legend">{{ c.legend }}</div>
        <div class="state-current" :style="{ color: c.color }">{{ fmtNum(c.current) }}</div>
        <div class="state-meta">
          <div><span class="meta-label">周期峰值</span> {{ fmtNum(c.max) }}</div>
          <div><span class="meta-label">全周期出现</span> {{ fmtNum(c.total) }}</div>
        </div>
        <div v-if="c.state === 'Z' && c.max > 0" class="state-alert">
          持续 zombie 进程 {{ state.zombie_pids.length }} 个
        </div>
        <div v-if="c.state === 'D' && c.max > 0" class="state-alert">
          持续 D 状态进程 {{ state.long_d_pids.length }} 个（可能 I/O 卡住）
        </div>
      </div>
    </div>

    <!-- 活跃状态趋势（仅 R/D/Z/T，去掉 S/I 这两个"底色"状态） -->
    <h3 style="margin-top: 18px">活跃状态趋势（仅 R / D / Z / T）</h3>
    <p class="section-desc">
      去掉 S / I（占 99%+，会压平其它状态），
      只看真正"活跃"的 4 个状态在采样期内的变化。
      <strong>周期峰值</strong>指所有 cycle 中该状态进程数最多的一次；
      <strong>全周期出现</strong>指整个采样期所有 cycle 里该状态出现的累计次数。
    </p>
    <div ref="chartRef" class="state-chart" />

    <!-- 异常进程表 -->
    <div v-if="state.zombie_pids.length > 0 || state.long_d_pids.length > 0" class="abnormal-section">
      <h3 style="margin-top: 20px">异常进程（持续状态）</h3>

      <div v-if="state.zombie_pids.length > 0">
        <h4>Zombie 进程（{{ state.zombie_pids.length }} 个，全部 cycle 都处于 Z 状态）</h4>
        <table class="abnormal-table">
          <thead>
            <tr>
              <th>PID</th>
              <th>USER</th>
              <th>COMMAND</th>
              <th>Z 状态 cycle</th>
              <th>持续</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in state.zombie_pids" :key="p.pid">
              <td>{{ p.pid }}</td>
              <td><code class="user-tag">{{ p.user }}</code></td>
              <td><code class="cmd-cell" :title="p.command">{{ shortCmd(p.command, 60) }}</code></td>
              <td>{{ p.cycles_z }}</td>
              <td class="ts-cell">{{ p.first_seen }} → {{ p.last_seen }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="state.long_d_pids.length > 0" style="margin-top: 16px">
        <h4>持续 D 状态进程（{{ state.long_d_pids.length }} 个，I/O 阻塞）</h4>
        <table class="abnormal-table">
          <thead>
            <tr>
              <th>PID</th>
              <th>USER</th>
              <th>COMMAND</th>
              <th>D 状态 cycle</th>
              <th>持续</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in state.long_d_pids" :key="p.pid">
              <td>{{ p.pid }}</td>
              <td><code class="user-tag">{{ p.user }}</code></td>
              <td><code class="cmd-cell" :title="p.command">{{ shortCmd(p.command, 60) }}</code></td>
              <td>{{ p.cycles_d }}</td>
              <td class="ts-cell">{{ p.first_seen }} → {{ p.last_seen }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.state-panel {
  width: 100%;
}

/* ─── 状态含义速查 ─── */
.state-legend-block {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 8px 14px;
  margin-bottom: 14px;
}
.state-legend-block summary {
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  user-select: none;
  padding: 4px 0;
}
.legend-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  margin-top: 8px;
}
.legend-table th,
.legend-table td {
  text-align: left;
  padding: 4px 8px;
  border-bottom: 1px solid #e5e7eb;
  vertical-align: top;
}
.legend-table th {
  color: #6b7280;
  font-weight: 600;
  font-size: 11px;
  background: white;
}
.legend-table tr:last-child td { border-bottom: none; }
.legend-table td.abnormal {
  color: #dc2626;
  font-weight: 500;
}
.state-code-inline {
  display: inline-block;
  width: 18px;
  height: 18px;
  line-height: 18px;
  text-align: center;
  border-radius: 3px;
  color: white;
  font-weight: 700;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  margin-right: 4px;
}
.state-legend-name {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  color: #374151;
}

/* ─── 7 张状态卡片 ─── */
.state-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 8px;
  margin-bottom: 8px;
}
.state-card {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-left-width: 4px;
  border-radius: 6px;
  padding: 8px 12px;
  position: relative;
  cursor: help;
}
.state-card.state-card-abnormal {
  background: #fef2f2;
}
.state-card:hover {
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}
.state-code {
  display: inline-block;
  width: 22px;
  height: 22px;
  line-height: 22px;
  text-align: center;
  border-radius: 4px;
  color: white;
  font-weight: 700;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 13px;
  margin-right: 6px;
  vertical-align: middle;
}
.state-legend {
  display: inline-block;
  font-size: 12px;
  color: #6b7280;
  vertical-align: middle;
}
.state-current {
  font-size: 22px;
  font-weight: 700;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  margin-top: 4px;
  line-height: 1.1;
}
.state-meta {
  font-size: 11px;
  color: #6b7280;
  margin-top: 4px;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.meta-label {
  color: #9ca3af;
  margin-right: 4px;
  font-size: 10px;
}
.state-alert {
  margin-top: 4px;
  font-size: 11px;
  color: #dc2626;
  font-weight: 500;
}

.state-chart {
  width: 100%;
  height: 240px;
  background: white;
  border-radius: 8px;
  padding: 8px;
}

.section-desc {
  color: #6b7280;
  font-size: 12px;
  margin-bottom: 8px;
}
.section-desc strong {
  color: #374151;
}

/* ─── 异常进程表 ─── */
.abnormal-section {
  margin-top: 16px;
}
.abnormal-section h3 {
  font-size: 14px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 8px;
}
.abnormal-section h4 {
  font-size: 13px;
  font-weight: 600;
  color: #991b1b;
  margin-bottom: 6px;
}

.abnormal-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  background: white;
  border: 1px solid #fecaca;
  border-radius: 4px;
  overflow: hidden;
}
.abnormal-table th,
.abnormal-table td {
  text-align: left;
  padding: 4px 8px;
  border-bottom: 1px solid #fef2f2;
}
.abnormal-table th {
  color: #991b1b;
  font-weight: 600;
  background: #fef2f2;
  font-size: 11px;
}
.abnormal-table tbody tr:last-child td { border-bottom: none; }
.abnormal-table .ts-cell { font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 10px; color: #6b7280; }

.user-tag {
  background: #eff6ff;
  color: #1e3a8a;
  padding: 0 6px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
}
.cmd-cell {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  color: #374151;
  word-break: break-all;
}
</style>
