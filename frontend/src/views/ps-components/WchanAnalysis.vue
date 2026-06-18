<script setup lang="ts">
/**
 * WCHAN 分析组件
 *
 * 4 部分：
 *   1. 含义速查（默认折叠）
 *   2. 6 张分类卡（running / io / lock / net / timer / other）+ 当前/峰值
 *   3. 横版条形图（6 类别全显示）
 *   4. 占比饼图（Top WCHAN，hover 显示 wchan/类别/次数/占比）
 *   5. 卡住进程表（持续在 io / lock wchan ≥ 5 cycle）
 */
import { computed, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { PsWchanAnalysis } from '../../api/ps'

const props = defineProps<{
  wchan: PsWchanAnalysis
  totalCycles: number
}>()

const pieChartRef = ref<HTMLDivElement | null>(null)
let pieChartInstance: echarts.ECharts | null = null

const CAT_COLORS: Record<string, string> = {
  running: '#16a34a',  // 绿 - 运行中（健康）
  io:      '#dc2626',  // 红 - IO 阻塞（重点关注）
  lock:    '#ea580c',  // 橙 - 锁等待（关注）
  net:     '#3b82f6',  // 蓝 - 网络
  timer:   '#9ca3af',  // 灰 - 定时器（正常）
  other:   '#7c3aed',  // 紫 - 其它
}

const CAT_SHORT_DESC: Record<string, string> = {
  running: '运行中（R 状态）',
  io:      'IO 等待（重点）',
  lock:    '锁等待（关注）',
  net:     '网络',
  timer:   '定时器（正常）',
  other:   '其它',
}

interface CardData {
  cat: string
  desc: string
  fullDesc: string
  total: number
  max: number
  color: string
  isAbnormal: boolean
}

const cards = computed<CardData[]>(() => {
  return props.wchan.category_order.map((c) => ({
    cat: c,
    desc: CAT_SHORT_DESC[c],
    fullDesc: props.wchan.category_legend[c] ?? '',
    total: props.wchan.category_total[c] ?? 0,
    max: props.wchan.category_max[c] ?? 0,
    color: CAT_COLORS[c] ?? '#9ca3af',
    isAbnormal: c === 'io' || c === 'lock',
  }))
})

// 横版条形图数据：所有 6 个类别 + 按 total 降序
interface HBarRow {
  cat: string
  color: string
  desc: string
  total: number
  max: number
  pct: number
}

const hbarData = computed<HBarRow[]>(() => {
  const totalAll = props.wchan.category_order.reduce(
    (s, c) => s + (props.wchan.category_total[c] ?? 0),
    0,
  )
  return props.wchan.category_order
    .map((c) => ({
      cat: c,
      color: CAT_COLORS[c] ?? '#9ca3af',
      desc: CAT_SHORT_DESC[c] ?? '',
      total: props.wchan.category_total[c] ?? 0,
      max: props.wchan.category_max[c] ?? 0,
      pct: totalAll > 0
        ? ((props.wchan.category_total[c] ?? 0) / totalAll) * 100
        : 0,
    }))
    .sort((a, b) => b.total - a.total)
})

// 饼图 option：top_wchans 直接作为饼图数据
const pieOption = computed(() => {
  const data = props.wchan.top_wchans.map((tw) => ({
    name: tw.wchan,
    value: tw.count,
    itemStyle: { color: CAT_COLORS[tw.category] ?? '#9ca3af' },
  }))
  return {
    tooltip: {
      trigger: 'item' as const,
      backgroundColor: 'rgba(17, 24, 39, 0.95)',
      borderColor: 'transparent',
      textStyle: { color: 'white', fontSize: 12 },
      formatter: (p: any) => {
        const tw = props.wchan.top_wchans.find((x) => x.wchan === p.name)
        if (!tw) return p.name
        return [
          `<div style="font-weight:600;margin-bottom:4px">${tw.wchan}</div>`,
          `<div>类别：<span style="color:${CAT_COLORS[tw.category]};font-weight:600">${tw.category}</span></div>`,
          `<div>累计出现：<b>${fmtNumPlain(tw.count)}</b></div>`,
          `<div>占比：<b>${p.percent.toFixed(2)}%</b></div>`,
        ].join('')
      },
    },
    legend: {
      type: 'scroll' as const,
      orient: 'vertical' as const,
      right: 10,
      top: 20,
      bottom: 20,
      textStyle: { fontSize: 11, fontFamily: 'SF Mono, Menlo, Consolas, monospace' },
    },
    series: [
      {
        name: 'WCHAN 占比',
        type: 'pie' as const,
        radius: ['38%', '68%'],
        center: ['38%', '50%'],
        avoidLabelOverlap: true,
        itemStyle: { borderRadius: 3, borderColor: 'white', borderWidth: 2 },
        label: {
          show: true,
          formatter: '{b}\n{d}%',
          fontSize: 10,
          fontFamily: 'SF Mono, Menlo, Consolas, monospace',
        },
        labelLine: { show: true, length: 8, length2: 8 },
        emphasis: {
          label: { show: true, fontSize: 12, fontWeight: 'bold' as const },
          itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.3)' },
        },
        data,
      },
    ],
  }
})

function fmtNumPlain(n: number): string {
  return n.toLocaleString()
}

function initPieChart() {
  if (!pieChartRef.value) return
  if (pieChartInstance) pieChartInstance.dispose()
  pieChartInstance = echarts.init(pieChartRef.value)
  pieChartInstance.setOption(pieOption.value)
}

watch(() => props.wchan, () => { initPieChart() }, { deep: true, immediate: true })
watch(pieOption, () => {
  if (pieChartInstance) pieChartInstance.setOption(pieOption.value, { notMerge: true })
}, { deep: true })
onMounted(() => {
  // 兜底：如果 immediate watch 还没触发，onMounted 强制 init
  initPieChart()
})
window.addEventListener('resize', () => pieChartInstance?.resize())

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
  <div class="wchan-panel">
    <!-- 含义速查（默认折叠） -->
    <details class="wchan-legend-block">
      <summary>WCHAN 含义速查（点击展开）</summary>
      <table class="legend-table">
        <thead>
          <tr>
            <th>类别</th>
            <th>含义</th>
            <th>重点关注？</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in props.wchan.category_order" :key="c">
            <td>
              <span class="cat-code-inline" :style="{ background: CAT_COLORS[c] }">{{ c }}</span>
            </td>
            <td>{{ props.wchan.category_legend[c] }}</td>
            <td :class="{ abnormal: c === 'io' || c === 'lock' }">
              {{ c === 'io' || c === 'lock' ? '⚠️ 重点' : '一般' }}
            </td>
          </tr>
        </tbody>
      </table>
    </details>

    <!-- 6 张分类卡 -->
    <div class="cat-cards">
      <div
        v-for="c in cards"
        :key="c.cat"
        class="cat-card"
        :class="{ 'cat-card-abnormal': c.isAbnormal }"
        :style="{ borderColor: c.color }"
        :title="c.fullDesc"
      >
        <div class="cat-code" :style="{ background: c.color }">{{ c.cat }}</div>
        <div class="cat-desc">{{ c.desc }}</div>
        <div class="cat-current" :style="{ color: c.color }">{{ fmtNum(c.max) }}</div>
        <div class="cat-meta">峰值 · 全周期 {{ fmtNum(c.total) }}</div>
      </div>
    </div>

    <!-- 横版条形图（6 个类别全显示，无选择器） -->
    <h3 style="margin-top: 18px">WCHAN 类别统计（横版条形图）</h3>
    <p class="section-desc">
      6 个类别的全周期累计次数。柱长按总累计的百分比（6 类总和 = 100%），右侧显示峰值供参考。
    </p>
    <div v-if="hbarData.length > 0" class="hbar-chart">
      <div v-for="row in hbarData" :key="row.cat" class="hbar-row">
        <div class="hbar-label">
          <span class="cat-chip-dot" :style="{ background: row.color }" />
          <code class="hbar-cat">{{ row.cat }}</code>
          <span class="hbar-desc">{{ row.desc }}</span>
        </div>
        <div class="hbar-track">
          <div
            class="hbar-fill"
            :style="{ width: row.pct + '%', background: row.color }"
          />
          <span class="hbar-value">
            <strong>{{ fmtNum(row.total) }}</strong>
            <span class="hbar-pct">{{ row.pct.toFixed(1) }}%</span>
            <span class="hbar-peak">峰值 {{ fmtNum(row.max) }}</span>
          </span>
        </div>
      </div>
    </div>
    <div v-else class="empty">无 WCHAN 数据</div>

    <!-- WCHAN 占比饼图（hover 显示 wchan/类别/次数/占比） -->
    <h3 style="margin-top: 24px">WCHAN 分布（饼图）</h3>
    <p class="section-desc">
      按出现次数排序的 Top WCHAN 占比。鼠标悬停切片查看对应 WCHAN 的类别、累计出现次数和占比。
    </p>
    <div v-if="wchan.top_wchans.length === 0" class="empty">无 WCHAN 数据</div>
    <div v-else ref="pieChartRef" class="pie-chart" />

    <!-- 卡住进程表 -->
    <div v-if="wchan.stuck_pids.length > 0" class="stuck-section">
      <h3 style="margin-top: 24px">⚠️ 卡住进程（{{ wchan.stuck_pids.length }} 个，连续 ≥ 5 cycle 卡在 io / lock wchan）</h3>
      <p class="section-desc">
        这些进程持续在 IO 或锁等待，**可能存在 IO 阻塞 / 锁竞争**，建议结合 iostat / vmstat 综合分析。
      </p>
      <table class="stuck-table">
        <thead>
          <tr>
            <th>PID</th>
            <th>USER</th>
            <th>COMMAND</th>
            <th>WCHAN</th>
            <th>类别</th>
            <th>卡住 cycle</th>
            <th>持续</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in wchan.stuck_pids" :key="p.pid">
            <td>{{ p.pid }}</td>
            <td><code class="user-tag">{{ p.user }}</code></td>
            <td><code class="cmd-cell" :title="p.command">{{ shortCmd(p.command, 50) }}</code></td>
            <td><code class="wchan-code">{{ p.wchan }}</code></td>
            <td>
              <span
                class="cat-tag"
                :style="{ background: CAT_COLORS[p.category], color: 'white' }"
              >{{ p.category }}</span>
            </td>
            <td>{{ p.cycles }}</td>
            <td class="ts-cell">{{ p.first_seen }} → {{ p.last_seen }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script lang="ts">
import { computed as _computed } from 'vue'
export default {}
</script>

<style scoped>
.wchan-panel {
  width: 100%;
}

/* ─── 含义速查 ─── */
.wchan-legend-block {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 8px 14px;
  margin-bottom: 14px;
}
.wchan-legend-block summary {
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
.cat-code-inline {
  display: inline-block;
  min-width: 50px;
  padding: 1px 8px;
  border-radius: 3px;
  color: white;
  font-weight: 600;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  text-align: center;
}

/* ─── 6 张分类卡 ─── */
.cat-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
  margin-bottom: 8px;
}
.cat-card {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-left-width: 4px;
  border-radius: 6px;
  padding: 8px 12px;
  cursor: help;
}
.cat-card.cat-card-abnormal {
  background: #fef2f2;
}
.cat-card:hover {
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}
.cat-code {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  color: white;
  font-weight: 700;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 13px;
  margin-right: 6px;
  vertical-align: middle;
}
.cat-desc {
  display: inline-block;
  font-size: 12px;
  color: #6b7280;
  vertical-align: middle;
}
.cat-current {
  font-size: 22px;
  font-weight: 700;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  margin-top: 4px;
  line-height: 1.1;
}
.cat-meta {
  font-size: 11px;
  color: #6b7280;
  margin-top: 4px;
}

/* ─── 类别选择器（chip 按钮组） ─── */
.cat-selector-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
  padding: 10px 12px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}
.cat-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.cat-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid #d1d5db;
  background: white;
  border-radius: 16px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.15s;
  user-select: none;
}
.cat-chip:hover {
  border-color: #93c5fd;
  background: #eff6ff;
}
.cat-chip.active {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
}
.cat-chip.active .cat-chip-dot {
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.4);
}
.cat-chip-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.cat-chip-name {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 12px;
  font-weight: 600;
}
.cat-selector-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.btn-mini {
  padding: 3px 10px;
  border: 1px solid #d1d5db;
  background: white;
  border-radius: 4px;
  cursor: pointer;
  font-size: 11px;
  color: #374151;
}
.btn-mini:hover {
  background: #f3f4f6;
  border-color: #9ca3af;
}
.selected-count {
  font-size: 11px;
  color: #6b7280;
  margin-left: auto;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}

/* ─── 横版条形图 ─── */
.hbar-chart {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.hbar-row {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 12px;
  align-items: center;
}
.hbar-label {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.hbar-cat {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 12px;
  font-weight: 600;
  color: #1f2937;
  padding: 1px 6px;
  background: #f3f4f6;
  border-radius: 3px;
}
.hbar-desc {
  font-size: 11px;
  color: #6b7280;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hbar-track {
  position: relative;
  height: 24px;
  background: #f3f4f6;
  border-radius: 4px;
  overflow: hidden;
}
.hbar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease;
  min-width: 2px;
}
.hbar-value {
  position: absolute;
  top: 0;
  left: 8px;
  right: 8px;
  height: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  color: #1f2937;
  pointer-events: none;
}
.hbar-value strong {
  font-size: 13px;
}
.hbar-pct {
  color: #4b5563;
  font-weight: 500;
}
.hbar-peak {
  color: #6b7280;
  margin-left: auto;
  font-size: 10px;
}

/* ─── 饼图 ─── */
.pie-chart {
  width: 100%;
  height: 420px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 8px;
}

.section-desc {
  color: #6b7280;
  font-size: 12px;
  margin-bottom: 8px;
}

/* ─── Top 表 ─── */
.top-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  overflow: hidden;
}
.top-table th,
.top-table td {
  text-align: left;
  padding: 4px 8px;
  border-bottom: 1px solid #f3f4f6;
}
.top-table th {
  color: #6b7280;
  font-weight: 600;
  background: #f9fafb;
  font-size: 11px;
}
.top-table tbody tr:last-child td { border-bottom: none; }
.wchan-code {
  background: #f3f4f6;
  color: #1f2937;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
}
.cat-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 10px;
  font-weight: 600;
  text-align: center;
  min-width: 50px;
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

/* ─── 卡住进程表 ─── */
.stuck-section {
  margin-top: 16px;
}
.stuck-section h3 {
  font-size: 14px;
  font-weight: 600;
  color: #991b1b;
  margin-bottom: 8px;
}
.stuck-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  background: white;
  border: 1px solid #fecaca;
  border-radius: 6px;
  overflow: hidden;
}
.stuck-table th,
.stuck-table td {
  text-align: left;
  padding: 4px 8px;
  border-bottom: 1px solid #fef2f2;
}
.stuck-table th {
  color: #991b1b;
  font-weight: 600;
  background: #fef2f2;
  font-size: 11px;
}
.stuck-table tbody tr:last-child td { border-bottom: none; }
.stuck-table .ts-cell { font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 10px; color: #6b7280; }
.stuck-table .cmd-cell { font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 11px; color: #374151; word-break: break-all; }
.stuck-table .user-tag { background: #eff6ff; color: #1e3a8a; padding: 0 6px; border-radius: 3px; font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 11px; }
</style>
