<script setup lang="ts">
/**
 * TopView · oswtop 工具专用（时间点驱动的进程探查器）
 *
 * 单一目标：选时间点 → 看进程列表 → 点行看该进程在前后时间的变化。
 *
 * 流程：
 *   1. 加载文件 → /api/top/analyze（取 timestamps 列表 + 上下文指标）
 *   2. 拖动时间滑块（或点 prev/next）→ /api/top/snapshot 取该 cycle 的进程列表
 *   3. 点击某行 → /api/top/pid_history 取该 PID 的全周期时序
 *
 * 不再有 8 章节布局：系统指标 grid / 用户分布 / 进程状态 / 结论 都不要。
 * 上下文只保留"当前时间点的系统摘要"（load avg / cpu / mem），作为时间滑块旁的 inline 信息。
 */
import { ref, computed, onMounted, watch } from 'vue'
import * as echarts from 'echarts'
import { ApiError, commonApi } from '../api/common'
import {
  topApi,
  type TopInfoResponse,
  type TopSnapshotResponse,
  type TopPidHistoryResponse,
  type TopLandscapeResponse,
  type TopVersionInfo,
  type UnknownFormatDetail,
} from '../api/top'
import FileSelector from '../components/FileSelector.vue'
import UnknownFormatDialog from '../components/UnknownFormatDialog.vue'
import UploadResultDialog from '../components/UploadResultDialog.vue'
import TimelineChart from '../components/TimelineChart.vue'

const dirPath = ref('')
const files = ref<string[]>([])
const selectedFile = ref<string | null>(null)
const analysis = ref<TopInfoResponse | null>(null)
const loading = ref(false)
const error = ref('')

const unknownFormatInfo = ref<UnknownFormatDetail | null>(null)

interface UploadedItem { original: string; saved_as: string; path: string }
interface FailedItem { filename: string; reason: string }
const uploadResult = ref<{ uploaded: UploadedItem[]; failed: FailedItem[] } | null>(null)

const supportedVersions = ref<TopVersionInfo[]>([])
onMounted(async () => {
  try {
    const res = await topApi.listTopVersions()
    supportedVersions.value = res.versions.filter((v) => v.active !== false)
  } catch {
    // 静默失败
  }
})

// ─── 选中的时间点 + 快照 ──────────────────────────────
const currentCycleIndex = ref(0)
const snapshot = ref<TopSnapshotResponse | null>(null)
const snapshotLoading = ref(false)
const snapshotError = ref('')

// 进程表的时间输入框（绑 v-model，独立于 currentCycleIndex）
// 用户输入时间戳 → 防抖 300ms → 反查 timestamps → 设 currentCycleIndex
// currentCycleIndex 变 → 触发 loadSnapshot → snapshot.timestamp 变 → 同步此值
const snapshotTimeInput = ref<string>('')
let snapshotTimeDebounceTimer: number | null = null

const timestamps = computed<string[]>(() => analysis.value?.timestamps ?? [])
const totalCycles = computed(() => timestamps.value.length)

watch(currentCycleIndex, async (idx) => {
  if (!analysis.value || idx < 0 || idx >= totalCycles.value) return
  await loadSnapshot(idx)
})

// snapshot.timestamp 变 → 同步 snapshotTimeInput（仅在不一致时）
watch(() => snapshot.value?.timestamp, (ts) => {
  if (ts && ts !== snapshotTimeInput.value) {
    snapshotTimeInput.value = ts
  }
})

// snapshotTimeInput 变（防抖 300ms）→ 反查 cycle_index → 切 currentCycleIndex
watch(snapshotTimeInput, () => {
  if (snapshotTimeDebounceTimer) clearTimeout(snapshotTimeDebounceTimer)
  snapshotTimeDebounceTimer = window.setTimeout(() => {
    const ts = snapshotTimeInput.value.trim()
    if (!ts || !analysis.value) return
    const idx = analysis.value.timestamps.indexOf(ts)
    if (idx >= 0 && idx !== currentCycleIndex.value) {
      currentCycleIndex.value = idx
    }
  }, 300)
})

async function loadSnapshot(idx: number) {
  if (!analysis.value || !selectedFile.value) return
  snapshotLoading.value = true
  snapshotError.value = ''
  try {
    snapshot.value = await topApi.snapshot(dirPath.value, selectedFile.value, idx)
  } catch (e: any) {
    snapshotError.value = e?.message ?? String(e)
    snapshot.value = null
  } finally {
    snapshotLoading.value = false
  }
}

// ─── 第 3 段：按 PID 查看（点击行 / 输入 PID 都触发这里）───────────


const searchedPidInput = ref<string>('')  // 输入框的值
const pidDetail = ref<TopPidHistoryResponse | null>(null)
const pidDetailLoading = ref(false)
const pidDetailError = ref('')
let pidSearchTimer: number | null = null

// 第 3 段自带动时间轴（独立于第 1 段全局 currentCycleIndex）
// 选 PID 后默认 0；用户拖动 slider / 输入时间戳独立切换
const pidTimeIndex = ref(0)
const pidTimeInput = ref<string>('')
let pidTimeDebounceTimer: number | null = null

// pidTimeIndex 变 → 自动同步 pidTimeInput（显示对应时间戳）
watch(pidTimeIndex, () => {
  if (!pidDetail.value) return
  const row = pidDetail.value.history.find(h => h.cycle_index === pidTimeIndex.value)
  pidTimeInput.value = row ? row.timestamp : ''
})

// pidTimeInput 变（防抖 300ms）→ 反查 cycle_index → 切 pidTimeIndex
watch(pidTimeInput, () => {
  if (pidTimeDebounceTimer) clearTimeout(pidTimeDebounceTimer)
  pidTimeDebounceTimer = window.setTimeout(() => {
    if (!pidDetail.value) return
    const ts = pidTimeInput.value.trim()
    if (!ts) return
    const row = pidDetail.value.history.find(h => h.timestamp === ts)
    if (row) pidTimeIndex.value = row.cycle_index
  }, 300)
})

// PID 变化时重置时间轴到 0
watch(() => pidDetail.value?.pid, (newPid, oldPid) => {
  if (newPid !== oldPid) {
    pidTimeIndex.value = 0
  }
})

// 当前 cycle 在该 PID 历史中的那一行（用于内联显示"该时间点该进程的状态"）
const currentPidRow = computed(() => {
  if (!pidDetail.value) return null
  return pidDetail.value.history.find(h => h.cycle_index === pidTimeIndex.value) || null
})

// 3 个 mini chart 的 series
function buildPidSeries(field: 'cpu_pct' | 'mem_pct' | 'res_kb'): { name: string; data: [string, number][] }[] {
  if (!pidDetail.value) return []
  return [{
    name: field,
    data: pidDetail.value.history.map(h => [h.timestamp, (h as any)[field] ?? 0] as [string, number]),
  }]
}

async function searchPid() {
  if (!analysis.value || !selectedFile.value) return
  const trimmed = searchedPidInput.value.trim()
  if (!trimmed) {
    pidDetail.value = null
    pidDetailError.value = ''
    return
  }
  const pid = parseInt(trimmed, 10)
  if (isNaN(pid)) {
    pidDetailError.value = 'PID 必须是数字'
    pidDetail.value = null
    return
  }
  pidDetailLoading.value = true
  pidDetailError.value = ''
  try {
    pidDetail.value = await topApi.pidHistory(dirPath.value, selectedFile.value, pid)
    if (pidDetail.value && pidDetail.value.cycles_seen === 0) {
      pidDetailError.value = `PID ${pid} 在文件中未出现`
    }
  } catch (e: any) {
    pidDetailError.value = e?.message ?? String(e)
    pidDetail.value = null
  } finally {
    pidDetailLoading.value = false
  }
}


watch(searchedPidInput, () => {
  if (pidSearchTimer) clearTimeout(pidSearchTimer)
  pidSearchTimer = window.setTimeout(searchPid, 300)
})

// 点击进程表的某行 → 自动填到搜索框（触发上面的 watch → 加载历史）
function openProcessDetail(pid: number) {
  searchedPidInput.value = String(pid)
}

function clearPidSearch() {
  searchedPidInput.value = ''
  pidDetail.value = null
  pidDetailError.value = ''
  pidTimeIndex.value = 0
  pidTimeInput.value = ''
}

// ─── 文件 IO ─────────────────────────────────────

async function scan() {
  if (!dirPath.value.trim()) return
  loading.value = true
  error.value = ''
  unknownFormatInfo.value = null
  try {
    const res = await topApi.scan(dirPath.value.trim())
    files.value = res.files
    selectedFile.value = null
    analysis.value = null
    snapshot.value = null
  } catch (e: any) {
    error.value = e?.message ?? String(e)
  } finally {
    loading.value = false
  }
}

async function scanUploadDir() {
  loading.value = true
  error.value = ''
  unknownFormatInfo.value = null
  try {
    const res = await topApi.scan('', 'top')
    dirPath.value = res.scanned_dir
    files.value = res.files
    selectedFile.value = null
    analysis.value = null
    snapshot.value = null
    if (res.cleaned_count > 0) {
      console.info(`[cleanup] 已清理 ${res.cleaned_count} 个超过 7 天的过期文件`)
    }
  } catch (e: any) {
    error.value = e?.message ?? String(e)
  } finally {
    loading.value = false
  }
}

async function onUpload(e: Event) {
  const target = e.target as HTMLInputElement
  if (!target.files || target.files.length === 0) return
  loading.value = true
  error.value = ''
  try {
    const res = await commonApi.uploadFiles(target.files, 'top')
    console.info(`[upload] 成功 ${res.uploaded_count} 个，失败 ${res.failed_count} 个`)
    if (res.uploaded_count > 0 || res.failed_count > 0) {
      uploadResult.value = { uploaded: res.uploaded, failed: res.failed }
    }
    if (res.uploaded_count > 0) {
      await scanUploadDir()
    }
  } catch (e: any) {
    error.value = e?.message ?? String(e)
  } finally {
    target.value = ''
    loading.value = false
  }
}

async function runAnalysis() {
  if (!selectedFile.value) return
  loading.value = true
  error.value = ''
  unknownFormatInfo.value = null
  try {
    analysis.value = await topApi.info(dirPath.value, selectedFile.value)
    // 重置时间点 + 加载第一个 snapshot
    currentCycleIndex.value = 0
    if (analysis.value) {
      await loadSnapshot(0)
      // 触发 landscape 默认加载（%CPU + %MEM, avg, 无 PID）
      await loadLandscape()
      // 加载第 2 段程序占用 TOP 20
      await loadTopPrograms()
    }
  } catch (e: any) {
    if (e instanceof ApiError && e.status === 422) {
      const detail = e.detail as UnknownFormatDetail | undefined
      if (detail && (detail as any).error === 'unknown_format') {
        unknownFormatInfo.value = detail
        loading.value = false
        return
      }
    }
    error.value = e?.message ?? String(e)
  } finally {
    loading.value = false
  }
}

function onFileToggle(f: string) {
  if (selectedFile.value === f) {
    selectedFile.value = null
  } else {
    selectedFile.value = f
  }
}


function onSelectAll() {
  if (files.value.length > 0) selectedFile.value = files.value[0]
}
function onDeselectAll() {
  selectedFile.value = null
}

// ─── 表格排序 ─────────────────────────────────────

type SortKey = 'pid' | 'user' | 'pr' | 'ni' | 'virt_kb' | 'res_kb' | 'shr_kb'
  | 's' | 'cpu_pct' | 'mem_pct' | 'time_str' | 'command'
const sortKey = ref<SortKey>('cpu_pct')
const sortDesc = ref(true)

const sortedProcesses = computed(() => {
  if (!snapshot.value) return []
  const arr = [...snapshot.value.processes]
  const k = sortKey.value
  const desc = sortDesc.value
  arr.sort((a, b) => {
    const va = (a as any)[k]
    const vb = (b as any)[k]
    if (typeof va === 'number' && typeof vb === 'number') {
      return desc ? vb - va : va - vb
    }
    const sa = String(va ?? '')
    const sb = String(vb ?? '')
    return desc ? sb.localeCompare(sa) : sa.localeCompare(sb)
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
function sortIcon(k: SortKey): string {
  if (sortKey.value !== k) return ''
  return sortDesc.value ? ' ↓' : ' ↑'
}

// ─── 格式工具 ─────────────────────────────────────

function formatKB(kb: number): string {
  if (kb >= 1024 * 1024) return `${(kb / 1024 / 1024).toFixed(2)} G`
  if (kb >= 1024) return `${(kb / 1024).toFixed(1)} M`
  return `${Math.round(kb)} K`
}


const PROGRAM_METRICS = [
  { key: 'cpu_top5', label: 'CPU TOP 20 出现次数', unit: ' 次', source: 'cpu_top', valueKey: 'top5_count' },
  { key: 'mem_top5', label: '内存 TOP 20 出现次数', unit: ' 次', source: 'mem_top', valueKey: 'top5_count' },
] as const
type ProgramMetricKey = typeof PROGRAM_METRICS[number]['key']

const programMetric = ref<ProgramMetricKey>('cpu_top5')
const programBarData = ref<{ cpu_top: any[]; mem_top: any[]; cycle_count: number } | null>(null)
const programBarLoading = ref(false)
const programBarError = ref('')
const programChartRef = ref<HTMLDivElement | null>(null)
let programChartInstance: echarts.ECharts | null = null

function truncateProgramName(cmd: string): string {
  if (!cmd) return '(无)'
  const base = cmd.split(' ')[0]?.split('/').pop() || cmd
  return base.length > 30 ? base.slice(0, 28) + '..' : base
}

async function loadTopPrograms() {
  if (!analysis.value || !selectedFile.value) return
  programBarLoading.value = true
  programBarError.value = ''
  try {
    const res = await topApi.topPrograms(dirPath.value, selectedFile.value)
    programBarData.value = { cpu_top: res.cpu_top, mem_top: res.mem_top, cycle_count: res.cycle_count }
  } catch (e: any) {
    programBarError.value = e?.message ?? String(e)
    programBarData.value = null
  } finally {
    programBarLoading.value = false
  }
}

function buildProgramBarOption() {
  const m = PROGRAM_METRICS.find(x => x.key === programMetric.value)!
  const list = (programBarData.value as any)?.[m.source] ?? []
  // 截断到 20，按指标降序
  const sorted = [...list].sort((a, b) => (b[m.valueKey] ?? 0) - (a[m.valueKey] ?? 0)).slice(0, 20)
  // ECharts 横向条形图：yAxis category 数据需要 reverse 才能让最大值在上
  const categories = sorted.map(p => truncateProgramName(p.command)).reverse()
  const values = sorted.map(p => Number(p[m.valueKey] ?? 0)).reverse()
  return {
    grid: { left: 180, right: 80, top: 10, bottom: 24 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any[]) => {
        if (!params.length) return ''
        const idx = params[0].dataIndex  // 翻转后索引
        const realIdx = sorted.length - 1 - idx
        const p = sorted[realIdx]
        const totalCycles = (programBarData.value as any)?.cycle_count || 0
        const ratio = totalCycles > 0
          ? `（${(p.top5_count / totalCycles * 100).toFixed(1)}%）`
          : ''
        return `<strong>${p.command}</strong><br/>` +
          `user: ${p.user}<br/>` +
          `状态: ${p.state || 'S'}<br/>` +
          `<hr style="margin:4px 0;border:none;border-top:1px solid #ddd"/>` +
          `${m.label}: <strong>${p.top5_count} / ${totalCycles}</strong>${ratio}<br/>` +
          `cycles_seen: ${p.cycles_seen}<br/>` +
          `CPU max: ${p.cpu_pct_max}% · avg: ${p.cpu_pct_avg}%<br/>` +
          `MEM max: ${p.mem_pct_max}% · avg: ${p.mem_pct_avg}%<br/>` +
          `RES max: ${(p.res_kb_max / 1024).toFixed(0)} MB<br/>` +
          `首现: ${p.first_seen}<br/>` +
          `末现: ${p.last_seen}`
      },
    },
    xAxis: {
      type: 'value',
      name: m.unit.trim(),
      nameTextStyle: { fontSize: 11 },
      axisLabel: { fontSize: 11 },
    },
    yAxis: {
      type: 'category',
      data: categories,
      axisLabel: { fontSize: 11, fontFamily: 'SF Mono, Menlo, Consolas, monospace', color: '#374151' },
    },
    series: [{
      type: 'bar',
      data: values,
      itemStyle: { color: '#2563eb', borderRadius: [0, 3, 3, 0] },
      label: { show: true, position: 'right', fontSize: 11, color: '#1f2937', formatter: (p: any) => `${p.value}${m.unit}` },
    }],
  }
}

function renderProgramChart() {
  if (!programChartInstance) return
  programChartInstance.setOption(buildProgramBarOption(), true)
}

function initProgramChart() {
  if (!programChartRef.value) return
  if (programChartInstance) programChartInstance.dispose()
  programChartInstance = echarts.init(programChartRef.value)
  if (programBarData.value) renderProgramChart()
}

watch(
  () => programChartRef.value,
  (el) => { if (el) initProgramChart() },
  { flush: 'post' },
)
watch(programMetric, renderProgramChart)
watch(programBarData, () => { if (programChartInstance) renderProgramChart() })
window.addEventListener('resize', () => programChartInstance?.resize())

// 切换文件时重置
watch(selectedFile, () => {
  programBarData.value = null
  programBarError.value = ''
  if (programChartInstance) {
    programChartInstance.clear()
  }
})

// ─── 第 1 段 landscape 图：多指标 + 聚合 + PID 过滤 ──────

// 每个指标的简短定义（"这个指标代表什么"）
// 在 chip 悬停 tooltip 和每张图上方 caption 都用到
const AVAILABLE_METRICS: { key: string; label: string; desc: string }[] = [
  { key: 'cpu_pct', label: '%CPU',  desc: '进程 CPU 占用率（单核基准，多核可超 100%）' },
  { key: 'mem_pct', label: '%MEM',  desc: '物理内存占用百分比' },
  { key: 'virt_kb', label: 'VIRT',  desc: '虚拟内存总量（KB）' },
  { key: 'res_kb',  label: 'RES',   desc: '进程占用的物理内存（KB）' },
  { key: 'shr_kb',  label: 'SHR',   desc: '共享内存（KB）' },
  { key: 'pr',      label: 'PR',    desc: '调度优先级（20=普通，越小越优先）' },
  { key: 'ni',      label: 'NI',    desc: 'nice 值（-20~19，越小越优先）' },
  { key: 'load_1m', label: 'load 1m', desc: '系统 1 分钟平均负载（系统级）' },
]

// series.name → metric key 反查（series.name 形如 "%CPU (avg)" 或 "PID 123 · %CPU (avg)"）
const LABEL_TO_METRIC_KEY: Record<string, string> = {
  '%CPU': 'cpu_pct',
  '%MEM': 'mem_pct',
  'VIRT': 'virt_kb',
  'RES': 'res_kb',
  'SHR': 'shr_kb',
  'PR': 'pr',
  'NI': 'ni',
  'load 1m': 'load_1m',
}

function getMetricDescBySeriesName(seriesName: string): string {
  // 去掉 "PID N · " 前缀和 " (agg)" 后缀
  const stripped = seriesName.replace(/^PID \d+ · /, '').replace(/ \((avg|max|sum)\)$/, '')
  const key = LABEL_TO_METRIC_KEY[stripped]
  if (!key) return ''
  return AVAILABLE_METRICS.find(m => m.key === key)?.desc ?? ''
}

const selectedMetrics = ref<string[]>(['cpu_pct', 'mem_pct'])
const aggMode = ref<'avg' | 'max' | 'sum'>('avg')
// 第 3 段的 PID 搜索框（独立 ref，与 landscape 解耦）
const landscapeData = ref<TopLandscapeResponse | null>(null)
const landscapeLoading = ref(false)
const landscapeError = ref('')
let landscapeTimer: number | null = null

function toggleMetric(key: string) {
  const idx = selectedMetrics.value.indexOf(key)
  if (idx >= 0) selectedMetrics.value.splice(idx, 1)
  else selectedMetrics.value.push(key)
}
function isMetricSelected(key: string): boolean {
  return selectedMetrics.value.includes(key)
}

async function loadLandscape() {
  if (!analysis.value || !selectedFile.value) return
  const metrics = [...selectedMetrics.value]
  if (metrics.length === 0) {
    landscapeData.value = null
    return
  }
  landscapeLoading.value = true
  landscapeError.value = ''
  try {
    // 第 1 段：聚合所有进程（pid 固定 null，PID 搜索在第 3 段用 pid_history）
    landscapeData.value = await topApi.landscape(dirPath.value, selectedFile.value, {
      pid: null,
      metrics,
      agg: aggMode.value,
    })
  } catch (e: any) {
    landscapeError.value = e?.message ?? String(e)
    landscapeData.value = null
  } finally {
    landscapeLoading.value = false
  }
}

// 只在指标 / 聚合变化时重新加载（PID 搜索在第 3 段独立触发）
watch(
  [selectedMetrics, aggMode],
  () => {
    if (!analysis.value || !selectedFile.value) return
    if (landscapeTimer) clearTimeout(landscapeTimer)
    landscapeTimer = window.setTimeout(loadLandscape, 300)
  },
  { deep: true },
)

// 切换文件时重置 landscape
watch(selectedFile, () => {
  landscapeData.value = null
  landscapeError.value = ''
})

// 点击 landscape 图上的某个点 → 跳转到该时间点的 cycle
function onLandscapePointClick(ts: string) {
  const idx = timestamps.value.indexOf(ts)
  if (idx >= 0) {
    currentCycleIndex.value = idx
  }
}


// 注意：buildDetailSeries / tsInHistory / currentIsInDetail 旧 modal 用，
// 新版本（内联在第 3 段）改用 buildPidSeries + currentPidRow。旧代码已删除。
</script>

<template>
  <div class="top-view">
    <header class="header">
      <div v-if="supportedVersions.length" class="version-hint">
        <span class="version-hint-label">已支持 {{ supportedVersions.length }} 个 top 格式版本：</span>
        <span
          v-for="v in supportedVersions"
          :key="v.version"
          class="version-tag"
          :title="`${v.display_name}\n${v.notes || ''}`"
        >{{ v.version }}</span>
      </div>
    </header>

    <!-- 路径输入 + 扫描 -->
    <section class="section path-section">
      <div class="path-row">
        <input
          v-model="dirPath"
          type="text"
          class="path-input"
          placeholder="输入 OSW top 数据目录路径（留空扫描上传目录 oswupdownload_file/top/）"
          @keyup.enter="scan"
        />
        <button class="btn" :disabled="loading" @click="scan">刷新</button>
        <button class="btn" :disabled="loading" @click="scanUploadDir" title="扫描项目根下的 oswupdownload_file/top/，自动清理超过 7 天的文件">
          扫描上传目录
        </button>
        <label
          class="btn btn-success"
          :class="{ disabled: loading }"
          title="上传 .dat / .dat.gz 文件到后端"
        >
          上传文件
          <input
            type="file"
            multiple
            accept=".dat,.dat.gz"
            style="display: none"
            :disabled="loading"
            @change="onUpload"
          />
        </label>
        <button
          class="btn btn-primary"
          :disabled="loading || !selectedFile"
          @click="runAnalysis"
        >
          {{ analysis ? '重新分析' : '分析' }}
        </button>
      </div>
      <div v-if="loading" class="loading">分析中（首次 ~1s，缓存命中瞬时）...</div>
      <div v-if="error" class="error">{{ error }}</div>
      <div v-if="dirPath" class="current-dir">
        当前目录：<code>{{ dirPath }}</code>
      </div>
    </section>

    <!-- 文件列表 -->
    <section v-if="files.length" class="section">
      <h2>文件列表（已选 {{ selectedFile ? 1 : 0 }} / 共 {{ files.length }}）</h2>
      <FileSelector
        :files="files"
        :selected="selectedFile ? [selectedFile] : []"
        @toggle="onFileToggle"
        @select-all="onSelectAll"
        @deselect-all="onDeselectAll"
      />
    </section>

    <!-- 主视图（时间点驱动的探查器）-->
    <template v-if="analysis && totalCycles > 0">
      <div class="result-info">
        文件：<code>{{ selectedFile }}</code> · 共 <strong>{{ totalCycles }}</strong> 个采集周期 · 时间范围 {{ analysis.time_range.start }} → {{ analysis.time_range.end }}
        <span v-if="analysis.matched_versions && Object.keys(analysis.matched_versions).length" class="version-info">
          · 命中 {{ Object.keys(analysis.matched_versions).join(', ') }}
        </span>
      </div>

      <!-- 1. 时间滑块 + landscape -->
      <section class="section">
        <h2>1. 多指标趋势图（点图选时间）</h2>
        <p class="section-desc">
          选指标 → 选聚合方式 → 选 PID（可选）→ 大图展示整段时间趋势。<strong>在图上点选某个时间点</strong>，
          下方第 3 段会显示该时间点的进程列表。
        </p>

        <div class="time-controls">
          <span class="time-label">
            当前图表信息采集的时间段：
            <code>{{ analysis?.time_range?.start || '...' }} → {{ analysis?.time_range?.end || '...' }}</code>
            <span class="time-label-sub">（共 {{ totalCycles }} 个 cycle）</span>
          </span>
          <span class="time-hint">（在下方大图上点选时间点切换）</span>
        </div>

        <div class="landscape">
          <!-- 指标多选 -->
          <div class="metric-picker">
            <span class="metric-picker-label">选择要查看的指标：</span>
            <div class="metric-chips">
              <button
                v-for="m in AVAILABLE_METRICS"
                :key="m.key"
                class="metric-chip"
                :class="{ active: isMetricSelected(m.key) }"
                :title="m.desc"
                @click="toggleMetric(m.key)"
              >{{ m.label }}</button>
            </div>
            <span class="metric-count">已选 {{ selectedMetrics.length }} / {{ AVAILABLE_METRICS.length }}</span>
          </div>

          <!-- 聚合方式（无 PID 过滤时才有意义）-->
          <div class="filter-row">
            <label>
              聚合方式：
              <select v-model="aggMode">
                <option value="avg">平均 (avg)</option>
                <option value="max">最大 (max)</option>
                <option value="sum">求和 (sum)</option>
              </select>
            </label>
            <span class="pid-hint muted">聚合所有进程的指标（无 PID 过滤）。点下方任意小图切换时间点</span>
          </div>

          <div v-if="landscapeLoading" class="loading">加载 landscape 中...</div>
          <div v-if="landscapeError" class="error">{{ landscapeError }}</div>

          <!-- 一个指标一张小图（避免不同量纲的指标堆叠在一起）-->
          <div v-if="landscapeData && landscapeData.series.length" class="charts-grid">
            <div v-for="s in landscapeData.series" :key="s.name" class="chart-cell">
              <div v-if="getMetricDescBySeriesName(s.name)" class="chart-caption">
                {{ getMetricDescBySeriesName(s.name) }}
              </div>
              <TimelineChart
                :title="s.name"
                :series="[s]"
                :height="320"
                :on-point-click="onLandscapePointClick"
              />
            </div>
          </div>
          <div v-else-if="!landscapeLoading && selectedMetrics.length === 0" class="empty">
            请至少选择一个指标
          </div>
        </div>
      </section>

      <!-- 2. 整个时间段的程序占用 TOP 20 -->
      <section class="section">
        <h2>2. 整个时间段的程序占用 TOP 20</h2>
        <p class="section-desc">
          按 (command, user) 聚合，统计在多少个 cycle 出现在该指标（CPU/内存）前 5 名，
          反映"哪个程序在整段时间里持续占资源"。切换下方指标切换排序依据。
        </p>

        <div class="metric-picker">
          <span class="metric-picker-label">排序指标：</span>
          <div class="metric-chips">
            <button
              v-for="m in PROGRAM_METRICS"
              :key="m.key"
              class="metric-chip"
              :class="{ active: programMetric === m.key }"
              @click="programMetric = m.key"
            >{{ m.label }}</button>
          </div>
        </div>

        <div v-if="programBarLoading" class="loading">加载 TOP 20 中...</div>
        <div v-if="programBarError" class="error">{{ programBarError }}</div>

        <div
          v-show="!programBarLoading && !programBarError"
          ref="programChartRef"
          class="program-bar-chart"
          :style="{ height: (40 + 20 * 24) + 'px' }"
        ></div>
      </section>

      <!-- 3. 按 PID 查看 -->
      <section class="section">
        <h2>3. 按 PID 查看（输入 PID 或点下方表格行自动填入）</h2>
        <p class="section-desc">
          输入 PID 查看该进程在所有 cycle 的变化过程（CPU/MEM/RES 时序 + 详细记录）。
          也可以浏览下方"当前时间点的所有进程"表格，点行自动填入 PID。
        </p>

        <div class="pid-search-box">
          <label>
            PID：
            <input
              v-model="searchedPidInput"
              type="text"
              inputmode="numeric"
              placeholder="输入 PID（如 2523184）"
              class="pid-input"
            />
          </label>
          <button v-if="searchedPidInput" class="btn-mini" @click="clearPidSearch">清空</button>
          <span v-if="pidDetail" class="pid-hint">
            <template v-if="pidDetail.cycles_seen > 0">
              出现 <strong>{{ pidDetail.cycles_seen }}</strong> / {{ pidDetail.total_cycles }} cycles
              · 首现 cycle {{ pidDetail.first_seen_cycle }}
              · 末现 cycle {{ pidDetail.last_seen_cycle }}
            </template>
          </span>
        </div>

        <div v-if="pidDetailLoading" class="loading">加载 PID 历史中...</div>
        <div v-if="pidDetailError" class="error">{{ pidDetailError }}</div>

        <div v-if="pidDetail" class="pid-detail">
          <div class="pid-header">
            <h3>
              <code class="command-cell">{{ pidDetail.command || '(无 command)' }}</code>
              <span class="pid-tag">PID {{ pidDetail.pid }}</span>
              <code class="user-tag">{{ pidDetail.user }}</code>
            </h3>
          </div>

          <!-- 时间轴 + 时间输入 + 该时间点该 PID 详情 -->
          <div v-if="pidDetail" class="pid-current-row">
            <h4 v-if="pidDetail.cycles_seen > 1">该 PID 在指定时间点的状态详情</h4>
            <h4 v-else>该 PID 的状态详情（文件中仅出现 {{ pidDetail.cycles_seen }} 次）</h4>
            <div v-if="pidDetail.cycles_seen > 1" class="pid-time-controls">
              <label class="pid-time-label">
                时间点
                <input
                  v-model.number="pidTimeIndex"
                  type="range"
                  :min="0"
                  :max="(pidDetail.total_cycles - 1)"
                  step="1"
                  class="pid-time-slider"
                />
                <code class="pid-time-display">{{ pidTimeInput || '—' }}</code>
              </label>
              <label class="pid-time-input-label">
                或直接输入：
                <input
                  v-model="pidTimeInput"
                  type="text"
                  placeholder="2026-06-07T01:00:03"
                  class="pid-time-input"
                />
              </label>
            </div>

            <table v-if="currentPidRow" class="data-table pid-row-table">
              <thead>
                <tr>
                  <th>PID</th><th>PR</th><th>NI</th>
                  <th>VIRT</th><th>RES</th><th>SHR</th>
                  <th>S</th><th>%CPU</th><th>%MEM</th><th>TIME+</th>
                  <th>COMMAND</th>
                </tr>
              </thead>
              <tbody>
                <tr :class="{ 'is-current': true }">
                  <td>{{ pidDetail.pid }}</td>
                  <td>{{ currentPidRow.pr }}</td>
                  <td>{{ currentPidRow.ni }}</td>
                  <td>{{ formatKB(currentPidRow.virt_kb) }}</td>
                  <td>{{ formatKB(currentPidRow.res_kb) }}</td>
                  <td>{{ formatKB(currentPidRow.shr_kb) }}</td>
                  <td><code class="state-tag" :class="`state-${currentPidRow.s}`">{{ currentPidRow.s }}</code></td>
                  <td class="num-cell">{{ currentPidRow.cpu_pct.toFixed(1) }}%</td>
                  <td class="num-cell">{{ currentPidRow.mem_pct.toFixed(1) }}%</td>
                  <td><code class="time-tag">{{ currentPidRow.time_str }}</code></td>
                  <td class="command-cell" :title="currentPidRow.command">{{ currentPidRow.command }}</td>
                </tr>
              </tbody>
            </table>
            <div v-else class="pid-current-missing">
              ⚠ PID {{ pidDetail.pid }} 在 cycle {{ pidTimeIndex + 1 }}（{{ pidTimeInput || '该 cycle 无该 PID 数据' }}）不存在（可能未启动或已退出）
            </div>
          </div>

          <!-- 3 个 mini chart -->
          <h4>该 PID 的全周期时序</h4>
          <div class="pid-charts">
            <TimelineChart
              title="CPU % 时序"
              :series="buildPidSeries('cpu_pct')"
              :height="180"
              unit=" %CPU"
            />
            <TimelineChart
              title="MEM % 时序"
              :series="buildPidSeries('mem_pct')"
              :height="180"
              unit=" %MEM"
            />
            <TimelineChart
              title="RES 时序"
              :series="buildPidSeries('res_kb')"
              :height="180"
              unit=" KB"
            />
          </div>

          <!-- 详细记录表 -->
          <details class="pid-history-details">
            <summary>详细记录（{{ pidDetail.history.length }} 条 · 点开查看完整列表）</summary>
            <div class="table-wrap">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>cycle</th>
                    <th>时间</th>
                    <th>%CPU</th>
                    <th>%MEM</th>
                    <th>RES</th>
                    <th>S</th>
                    <th>TIME+</th>
                    <th>COMMAND</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="h in pidDetail.history"
                    :key="h.cycle_index"
                    :class="{ 'is-current': h.cycle_index === currentCycleIndex }"
                  >
                    <td>{{ h.cycle_index }}</td>
                    <td><code class="time-tag">{{ h.timestamp }}</code></td>
                    <td class="num-cell">{{ h.cpu_pct.toFixed(1) }}%</td>
                    <td class="num-cell">{{ h.mem_pct.toFixed(1) }}%</td>
                    <td>{{ formatKB(h.res_kb) }}</td>
                    <td><code class="state-tag" :class="`state-${h.s}`">{{ h.s }}</code></td>
                    <td><code class="time-tag">{{ h.time_str }}</code></td>
                    <td class="command-cell">{{ h.command }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </details>
        </div>

        <div v-else-if="!pidDetailLoading && !searchedPidInput" class="empty">
          输入 PID 查看单个进程的全周期变化（点下方表格行也可自动填入）
        </div>

        <!-- 当前时间点的所有进程（点行 = 填入 PID） -->
        <h3 class="sub-section-title">或浏览当前时间点的所有进程（拖动下方进度条或直接输入时间切换时间点）</h3>
        <div v-if="snapshot" class="snapshot-progress">
          <code class="snapshot-progress-time">{{ snapshot.timestamp }}</code>
          <input
            v-model.number="currentCycleIndex"
            type="range"
            :min="0"
            :max="totalCycles - 1"
            step="1"
            class="snapshot-progress-slider"
            :style="{ '--progress': ((currentCycleIndex + 1) / totalCycles * 100) + '%' }"
          />
          <input
            v-model="snapshotTimeInput"
            type="text"
            placeholder="时间戳"
            class="snapshot-progress-input"
          />
          <span class="snapshot-progress-label">cycle {{ currentCycleIndex + 1 }} / {{ totalCycles }}</span>
        </div>
        <div v-if="snapshotLoading" class="loading">加载 snapshot 中...</div>
        <div v-if="snapshotError" class="error">{{ snapshotError }}</div>
        <div v-if="snapshot" class="snapshot-info">
          {{ snapshot.processes.length }} 个进程
        </div>
        <div v-if="snapshot" class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th class="sortable" @click="setSort('pid')">PID{{ sortIcon('pid') }}</th>
                <th class="sortable" @click="setSort('user')">USER{{ sortIcon('user') }}</th>
                <th class="sortable" @click="setSort('pr')">PR{{ sortIcon('pr') }}</th>
                <th class="sortable" @click="setSort('ni')">NI{{ sortIcon('ni') }}</th>
                <th class="sortable" @click="setSort('virt_kb')">VIRT{{ sortIcon('virt_kb') }}</th>
                <th class="sortable" @click="setSort('res_kb')">RES{{ sortIcon('res_kb') }}</th>
                <th class="sortable" @click="setSort('shr_kb')">SHR{{ sortIcon('shr_kb') }}</th>
                <th class="sortable" @click="setSort('s')">S{{ sortIcon('s') }}</th>
                <th class="sortable" @click="setSort('cpu_pct')">%CPU{{ sortIcon('cpu_pct') }}</th>
                <th class="sortable" @click="setSort('mem_pct')">%MEM{{ sortIcon('mem_pct') }}</th>
                <th class="sortable" @click="setSort('time_str')">TIME+{{ sortIcon('time_str') }}</th>
                <th class="sortable" @click="setSort('command')">COMMAND{{ sortIcon('command') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="p in sortedProcesses"
                :key="p.pid + '_' + p.command"
                class="process-row"
                :class="{ 'detail-open': Number(searchedPidInput) === p.pid }"
                @click="openProcessDetail(p.pid)"
                :title="`点击将 PID ${p.pid} 填入上方搜索框`"
              >
                <td>{{ p.pid }}</td>
                <td><code class="user-tag">{{ p.user }}</code></td>
                <td>{{ p.pr }}</td>
                <td>{{ p.ni }}</td>
                <td>{{ formatKB(p.virt_kb) }}</td>
                <td>{{ formatKB(p.res_kb) }}</td>
                <td>{{ formatKB(p.shr_kb) }}</td>
                <td><code class="state-tag" :class="`state-${p.s}`">{{ p.s }}</code></td>
                <td class="num-cell">{{ p.cpu_pct.toFixed(1) }}%</td>
                <td class="num-cell">{{ p.mem_pct.toFixed(1) }}%</td>
                <td><code class="time-tag">{{ p.time_str }}</code></td>
                <td class="command-cell" :title="p.command">{{ p.command }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <UnknownFormatDialog
      v-if="unknownFormatInfo"
      :banner="unknownFormatInfo.banner"
      :header-columns="unknownFormatInfo.header_columns"
      :pending-path="unknownFormatInfo.pending_path"
      @close="unknownFormatInfo = null"
    />
    <UploadResultDialog
      v-if="uploadResult"
      :uploaded="uploadResult.uploaded"
      :failed="uploadResult.failed"
      @close="uploadResult = null"
    />
  </div>
</template>

<style scoped>
.top-view {
  max-width: 1400px;
  margin: 0 auto;
  padding: 16px 24px 40px;
}


.version-hint { font-size: 12px; color: #666; }
.version-hint-label { margin-right: 4px; }
.version-tag {
  display: inline-block;
  background: #e0f2fe;
  color: #075985;
  padding: 1px 6px;
  border-radius: 3px;
  margin-right: 4px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  cursor: help;
}


.section h2 {
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
  border-left: 4px solid #2563eb;
  padding-left: 10px;
  margin-bottom: 12px;
}
.section h3 { font-size: 14px; font-weight: 600; color: #1e3a8a; margin: 16px 0 8px 0; }
.section h4 { font-size: 13px; font-weight: 600; color: #374151; margin: 16px 0 6px 0; }
.section-desc { font-size: 13px; color: #666; margin-bottom: 12px; line-height: 1.5; }

.path-section { background: #fff; border-radius: 8px; padding: 12px 16px; }
.path-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.path-input {
  flex: 1;
  min-width: 280px;
  padding: 6px 10px;
  border: 1px solid #d0d0d0;
  border-radius: 4px;
  font-size: 13px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
.btn {
  padding: 6px 14px;
  border: 1px solid #d0d0d0;
  background: #fff;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  white-space: nowrap;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: #1976d2; color: #fff; border-color: #1976d2; }
.btn-primary:hover:not(:disabled) { background: #1565c0; }
.btn-success { background: #16a34a; color: #fff; border-color: #16a34a; cursor: pointer; }
.btn-success:hover:not(.disabled) { background: #15803d; }
.btn-success.disabled { opacity: 0.5; cursor: not-allowed; }
.btn-mini {
  padding: 3px 8px;
  border: 1px solid #d0d0d0;
  background: #fff;
  border-radius: 3px;
  cursor: pointer;
  font-size: 11px;
}
.btn-mini:hover:not(:disabled) { background: #f3f4f6; }
.btn-mini:disabled { opacity: 0.4; cursor: not-allowed; }

.loading { margin-top: 8px; color: #1976d2; font-size: 13px; }
.error { margin-top: 8px; color: #dc2626; font-size: 13px; }
.current-dir {
  margin-top: 8px;
  font-size: 12px;
  color: #888;
}
.current-dir code {
  background: #f5f5f5;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}

.result-info {
  margin: 16px 0;
  padding: 10px 14px;
  background: #f0f4ff;
  border-radius: 6px;
  font-size: 13px;
  color: #374151;
}
.result-info code { font-family: 'SF Mono', Menlo, Consolas, monospace; }
.version-info { color: #6b7280; margin-left: 4px; }

/* 时间显示条 */
.time-controls {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.time-label {
  font-size: 13px;
  color: #374151;
  margin: 0 4px;
}
.time-label code { font-family: 'SF Mono', Menlo, Consolas, monospace; }
.time-hint {
  font-size: 12px;
  color: #9ca3af;
  font-style: italic;
  margin-left: 4px;
}
.landscape {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 12px 14px;
  margin-top: 8px;
}
.metric-picker {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.metric-picker-label {
  font-size: 13px;
  color: #4b5563;
  font-weight: 500;
  white-space: nowrap;
}
.metric-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.metric-chip {
  display: inline-block;
  padding: 4px 12px;
  border: 1px solid #d0d0d0;
  background: #fff;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  color: #4b5563;
  transition: all 0.1s;
  user-select: none;
}
.metric-chip:hover {
  border-color: #93c5fd;
  background: #f0f9ff;
  color: #1e3a8a;
}
.metric-chip.active {
  background: #2563eb;
  color: #fff;
  border-color: #2563eb;
  font-weight: 600;
}
.metric-chip.active:hover {
  background: #1d4ed8;
  border-color: #1d4ed8;
  color: #fff;
}
.metric-count {
  margin-left: auto;
  font-size: 12px;
  color: #6b7280;
}
.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(600px, 1fr));
  gap: 12px;
  margin-top: 6px;
}
.chart-cell {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 4px 6px 8px 6px;
}
.chart-caption {
  font-size: 12px;
  line-height: 1.55;
  color: #4b5563;
  padding: 6px 8px;
  background: #f9fafb;
  border-bottom: 1px dashed #e5e7eb;
  border-radius: 4px 4px 0 0;
}
.filter-row {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
  padding: 8px 10px;
  background: #f9fafb;
  border-radius: 4px;
  margin-bottom: 10px;
  font-size: 13px;
}
.filter-row label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #4b5563;
}
.filter-row select,
.filter-row input {
  padding: 3px 8px;
  border: 1px solid #d0d0d0;
  border-radius: 3px;
  font-size: 12px;
  background: #fff;
}
.filter-row .pid-search input {
  width: 200px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
.pid-hint {
  font-size: 12px;
  color: #4b5563;
  margin-left: auto;
}
.pid-hint.muted { color: #9ca3af; font-style: italic; }
.pid-warn { color: #b91c1c; font-weight: 500; }

/* 第 2 段：TOP 20 程序占用条形图 */
.program-bar-chart {
  width: 100%;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  margin-top: 8px;
}


.snapshot-info {
  margin-bottom: 8px;
  padding: 6px 10px;
  background: #f9fafb;
  border-radius: 4px;
  font-size: 12px;
  color: #4b5563;
}
.snapshot-info code { font-family: 'SF Mono', Menlo, Consolas, monospace; }

.data-table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  overflow: hidden;
  font-size: 13px;
}
.data-table th, .data-table td {
  text-align: left;
  padding: 6px 10px;
  border-bottom: 1px solid #f3f4f6;
}
.data-table th {
  background: #f9fafb;
  font-weight: 500;
  color: #374151;
  font-size: 12px;
}
.data-table th.sortable { cursor: pointer; user-select: none; }
.data-table th.sortable:hover { background: #f3f4f6; }
.data-table tr:last-child td { border-bottom: none; }

.process-row { cursor: pointer; transition: background 0.1s; }
.process-row:hover td { background: #eff6ff; }
.process-row.detail-open td { background: #dbeafe; }

.user-tag {
  background: #f0f4ff;
  color: #1e3a8a;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
.state-tag {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-weight: 600;
}
.state-R { background: #dcfce7; color: #14532d; }
.state-S { background: #f3f4f6; color: #374151; }
.state-D { background: #fee2e2; color: #991b1b; }
.state-Z { background: #1f2937; color: #f3f4f6; }
.state-T { background: #fef3c7; color: #92400e; }
.state-I { background: #dbeafe; color: #1e40af; }
.time-tag {
  background: #f5f5f5;
  color: #555;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
.num-cell { text-align: right; font-family: 'SF Mono', Menlo, Consolas, monospace; }
.command-cell {
  max-width: 380px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 12px;
  color: #1f2937;
}
.table-wrap { max-height: 600px; overflow: auto; }
.is-current { background: #fef3c7 !important; }
.is-current td { background: #fef3c7 !important; }

/* Modal */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}
.modal-card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  width: min(1100px, 96vw);
  max-height: 92vh;
  overflow-y: auto;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.25);
}


.pid-search-box {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 10px;
  padding: 10px 12px;
  background: #eff6ff;
  border-radius: 6px;
  border: 1px solid #bfdbfe;
}
.pid-tag {
  background: #1e3a8a;
  color: #fff;
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 13px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
.pid-input {
  width: 180px;
  padding: 5px 8px;
  border: 1px solid #d0d0d0;
  border-radius: 3px;
  font-size: 13px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  background: #fff;
}
.pid-detail {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 12px 14px;
  margin-bottom: 12px;
}
.pid-detail h3 {
  font-size: 16px;
  margin: 0 0 6px 0;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.pid-detail h4 {
  font-size: 13px;
  font-weight: 600;
  color: #1e3a8a;
  margin: 14px 0 6px 0;
}
.pid-row-table {
  margin-bottom: 4px;
}
.pid-current-missing {
  background: #fffbeb;
  border: 1px solid #fed7aa;
  border-radius: 4px;
  padding: 8px 12px;
  margin: 8px 0;
  color: #92400e;
  font-size: 13px;
}
.pid-time-controls {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
  padding: 8px 12px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  margin-bottom: 8px;
  font-size: 13px;
}
.pid-time-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #374151;
  min-width: 360px;
}
.pid-time-slider {
  flex: 1;
  min-width: 180px;
  cursor: pointer;
}
.pid-time-display {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 13px;
  background: #fff;
  padding: 3px 8px;
  border: 1px solid #93c5fd;
  border-radius: 3px;
  color: #1e3a8a;
  white-space: nowrap;
}
.pid-time-input-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #4b5563;
}
.pid-time-input {
  width: 200px;
  padding: 4px 8px;
  border: 1px solid #d0d0d0;
  border-radius: 3px;
  font-size: 12px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  background: #fff;
}
.pid-time-hint {
  font-size: 12px;
  color: #6b7280;
  font-style: italic;
}
.pid-charts {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}
.pid-history-details {
  margin-top: 12px;
}
.pid-history-details summary {
  cursor: pointer;
  font-size: 13px;
  color: #4b5563;
  font-weight: 500;
  padding: 4px 0;
}
.pid-history-details[open] summary {
  margin-bottom: 8px;
}
.sub-section-title {
  font-size: 15px;
  font-weight: 600;
  color: #1f2937;
  margin: 20px 0 10px 0;
  padding-top: 14px;
  border-top: 1px solid #e5e7eb;
}
.sub-section-time {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 13px;
  background: #eff6ff;
  border: 1px solid #93c5fd;
  border-radius: 3px;
  padding: 2px 6px;
  color: #1e3a8a;
  margin: 0 2px;
}
.snapshot-progress {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  margin-bottom: 8px;
}
.snapshot-progress-time {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 12px;
  background: #eff6ff;
  border: 1px solid #93c5fd;
  border-radius: 3px;
  padding: 2px 6px;
  color: #1e3a8a;
  white-space: nowrap;
  flex-shrink: 0;
}
.snapshot-progress-slider {
  flex: 1;
  min-width: 200px;
  height: 14px;
  margin: 0 4px;
  appearance: none;
  -webkit-appearance: none;
  background: linear-gradient(
    to right,
    #2563eb 0%,
    #1d4ed8 var(--progress, 0%),
    #e5e7eb var(--progress, 0%),
    #e5e7eb 100%
  );
  border-radius: 7px;
  cursor: pointer;
  outline: none;
}
.snapshot-progress-slider::-webkit-slider-thumb {
  appearance: none;
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  background: #fff;
  border: 2px solid #1e3a8a;
  border-radius: 50%;
  cursor: grab;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
}
.snapshot-progress-slider::-webkit-slider-thumb:active { cursor: grabbing; }
.snapshot-progress-slider::-moz-range-thumb {
  width: 14px;
  height: 14px;
  background: #fff;
  border: 2px solid #1e3a8a;
  border-radius: 50%;
  cursor: grab;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
}
.snapshot-progress-input {
  width: 180px;
  padding: 3px 8px;
  border: 1px solid #d0d0d0;
  border-radius: 3px;
  font-size: 12px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  background: #fff;
  flex-shrink: 0;
}
.snapshot-progress-label {
  font-size: 12px;
  color: #6b7280;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  white-space: nowrap;
  flex-shrink: 0;
}
</style>
