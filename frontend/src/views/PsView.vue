<script setup lang="ts">
/**
 * PsView · oswps 工具专用（Oracle/RAC 故障排查）
 *
 * 按 8 核心字段组织（USER | PID | %CPU | RSS | STATE | WCHAN | STARTED | COMMAND）：
 *   - 一、总体概览：分类计数 + by_user 表
 *   - 二、核心指标时间线：9 张 metrics grid（按周期）
 *   - 三、进程 WCHAN：等待的内核函数（IO/Lock/Net/Timer）
 *   - 四、TOP 进程（核心 8 字段）：cpu_top ∪ mem_top 统一表，含全部 8 列
 *   - 五、USER 维度：by_user 聚合 + 按用户分组的 TOP 命令
 *   - 六、进程分类识别：Oracle / Grid / 系统 / 脚本
 *   - 七、生命周期（STARTED）：运行时长 + 重启
 *   - 八、结论与建议
 *
 * 注：原"进程状态（STATE 字段）"独立章节已删除，state 分析数据保留在
 *     后端响应里（用于结论中的 Z/D 异常检测）。
 */
import { ref, computed, onMounted, watch } from 'vue'
import { ApiError, commonApi } from '../api/common'
import {
  psApi,
  type PsAnalysisResponse,
  type PsVersionInfo,
  type UnknownFormatDetail,
} from '../api/ps'
import FileSelector from '../components/FileSelector.vue'
import UnknownFormatDialog from '../components/UnknownFormatDialog.vue'
import UploadResultDialog from '../components/UploadResultDialog.vue'
import TimelineChart from '../components/TimelineChart.vue'
import WchanAnalysis from './ps-components/WchanAnalysis.vue'
import CoreProcessTable from './ps-components/CoreProcessTable.vue'
import TopCommandsByUser from './ps-components/TopCommandsByUser.vue'
import ProgramRuntimeTable from './ps-components/ProgramRuntimeTable.vue'
import { buildMarkdownReport, downloadMarkdown } from './ps-components/markdownReport'

const dirPath = ref('')
const files = ref<string[]>([])
const selectedFile = ref<string | null>(null)
const analysis = ref<PsAnalysisResponse | null>(null)
const loading = ref(false)
const error = ref('')

const unknownFormatInfo = ref<UnknownFormatDetail | null>(null)

interface UploadedItem { original: string; saved_as: string; path: string }
interface FailedItem { filename: string; reason: string }
const uploadResult = ref<{ uploaded: UploadedItem[]; failed: FailedItem[] } | null>(null)

const supportedVersions = ref<PsVersionInfo[]>([])
onMounted(async () => {
  try {
    const res = await psApi.listPsVersions()
    supportedVersions.value = res.versions.filter((v) => v.active !== false)
  } catch {
    // 静默失败
  }
})

async function scan() {
  if (!dirPath.value.trim()) return
  loading.value = true
  error.value = ''
  unknownFormatInfo.value = null
  try {
    const res = await psApi.scan(dirPath.value.trim())
    files.value = res.files
    selectedFile.value = null
    analysis.value = null
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
    const res = await psApi.scan('', 'ps')
    dirPath.value = res.scanned_dir
    files.value = res.files
    selectedFile.value = null
    analysis.value = null
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
    const res = await commonApi.uploadFiles(target.files, 'ps')
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
    analysis.value = await psApi.analyze(dirPath.value, selectedFile.value)
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
  if (files.value.length > 0) {
    selectedFile.value = files.value[0]
  }
}

function onDeselectAll() {
  selectedFile.value = null
}

function formatKB(kb: number): string {
  if (kb >= 1024 * 1024) return `${(kb / 1024 / 1024).toFixed(2)} G`
  if (kb >= 1024) return `${(kb / 1024).toFixed(1)} M`
  return `${Math.round(kb)} K`
}

function onExportMarkdown() {
  if (!analysis.value) return
  const md = buildMarkdownReport(analysis.value, selectedFile.value || '')
  const baseName = (selectedFile.value || 'report').replace(/\.(dat|dat\.gz)$/, '')
  downloadMarkdown(md, `${baseName}_ps_report.md`)
}

// ─── 计算属性 ─────────────────────────────────────

const overview = computed(() => analysis.value?.overview)
const trends = computed(() => analysis.value?.trends)
const cpuTop = computed(() => analysis.value?.cpu_top ?? [])
const memTop = computed(() => analysis.value?.mem_top ?? [])
const oracle = computed(() => analysis.value?.oracle)
const grid = computed(() => analysis.value?.grid)
const system = computed(() => analysis.value?.system)
const userScripts = computed(() => analysis.value?.user_scripts ?? [])
const lifecycle = computed(() => analysis.value?.lifecycle ?? [])
const state = computed(() => analysis.value?.state)
const wchan = computed(() => analysis.value?.wchan)
const userTrends = computed(() => analysis.value?.user_trends)

// USER 选择（iostat 风格 multi-select，默认全选所有检测到的用户）
const selectedUsers = ref<string[]>([])

watch(
  userTrends,
  (ut) => {
    if (ut && selectedUsers.value.length === 0) {
      // 默认显示 Top 5 用户（按累计出现次数降序）
      selectedUsers.value = ut.users.slice(0, 5).map((u) => u.user)
    }
  },
  { immediate: true },
)

function toggleUser(u: string) {
  const idx = selectedUsers.value.indexOf(u)
  if (idx >= 0) selectedUsers.value.splice(idx, 1)
  else selectedUsers.value.push(u)
}

function isUserSelected(u: string): boolean {
  return selectedUsers.value.includes(u)
}

function selectAllUsers() {
  if (userTrends.value) selectedUsers.value = userTrends.value.users.map((u) => u.user)
}

function selectNoneUsers() {
  selectedUsers.value = []
}

function selectTopNUsers(n: number) {
  if (userTrends.value) selectedUsers.value = userTrends.value.users.slice(0, n).map((u) => u.user)
}

function buildSelectedUserSeries(): { name: string; data: [string, number][] }[] {
  if (!userTrends.value) return []
  return selectedUsers.value.map((u) => {
    const ts = userTrends.value!.by_cycle.map((r) => r.timestamp)
    const data = userTrends.value!.by_cycle.map((r) => r[u] ?? 0)
    return { name: `${u} 进程数`, data: ts.map((t, i) => [t, data[i]] as [string, number]) }
  })
}

function fmtNum(n: number): string {
  return n.toLocaleString()
}

const oracleBgEntries = computed(() => {
  if (!oracle.value) return []
  return Object.entries(oracle.value.background_counts)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
})

const gridKindEntries = computed(() => {
  if (!grid.value) return []
  return Object.entries(grid.value.kind_counts)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
})

const systemKindEntries = computed(() => {
  if (!system.value) return []
  return Object.entries(system.value.kind_peak)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
})

// ─── 11. 进程状态分析 ─────────────────────────────────────

interface MetricDef {
  key: string
  label: string       // 中文图例名
  desc: string        // 中文含义（显示在 chart unit 处）
  color?: string       // 可选颜色
}

const METRICS: MetricDef[] = [
  { key: 'total',         label: '总进程数',     desc: '所有进程总数（含 kernel / 系统）' },
  { key: 'oracle',        label: 'Oracle 进程',   desc: 'Oracle DB + ASM 进程' },
  { key: 'grid',          label: 'Grid 进程',     desc: 'Grid Infrastructure（ocssd/crsd/...）' },
  { key: 'kernel',        label: 'Kernel 线程',   desc: '内核线程（[kworker] / [migration] 等）' },
  { key: 'user',          label: '用户进程',      desc: '人类用户（UID 通常 ≥ 1000）' },
  { key: 'system_daemon', label: '系统守护',      desc: 'root 运行的系统服务' },
  { key: 'user_script',   label: '用户脚本',      desc: 'raid-check / rman / expdp / tar / gzip 等' },
  { key: 'px',            label: 'PX 并行',       desc: 'Oracle 并行执行（ora_p000..p999）' },
  { key: 'job',           label: 'Job 队列',      desc: 'Oracle CJQ0 + J000..J999' },
]

function buildMetricSeries(metricKey: string): { name: string; data: [string, number][] }[] {
  if (!trends.value) return []
  const ts = trends.value.timestamps
  const data = (trends.value as any)[metricKey] as number[] | undefined
  if (!data) return []
  const meta = METRICS.find((m) => m.key === metricKey)
  return [{
    name: meta?.label || metricKey,
    data: ts.map((t, i) => [t, data[i] ?? 0] as [string, number]),
  }]
}
</script>

<template>
  <div class="ps-view">
    <header class="header">
      <div v-if="supportedVersions.length" class="version-hint">
        <span class="version-hint-label">已支持 {{ supportedVersions.length }} 个 ps 格式版本：</span>
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
          placeholder="输入 OSW ps 数据目录路径（留空则扫描上传目录 oswupdownload_file/ps/），如 /data/osw/oswps/"
          @keyup.enter="scan"
        />
        <button class="btn" :disabled="loading" @click="scan">刷新</button>
        <button class="btn" :disabled="loading" @click="scanUploadDir" title="扫描项目根下的 oswupdownload_file/ps/，自动清理超过 7 天的文件">
          扫描上传目录
        </button>
        <label
          class="btn btn-success"
          :class="{ disabled: loading }"
          title="上传 .dat / .dat.gz 文件到后端，自动出现在文件列表中"
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
        <button
          v-if="analysis"
          class="btn btn-export"
          :disabled="loading"
          @click="onExportMarkdown"
          title="导出 Markdown 报告（一-八章节）"
        >
          导出 Markdown 报告
        </button>
      </div>
      <div v-if="loading" class="loading">分析中（首次 ~36s，缓存命中瞬时）...</div>
      <div v-if="error" class="error">{{ error }}</div>
      <div v-if="dirPath" class="current-dir">
        当前目录：<code>{{ dirPath }}</code>
      </div>
    </section>

    <!-- 文件列表（单选） -->
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

    <!-- 分析结果（10 章节） -->
    <template v-if="analysis">
      <div class="result-info">
        文件：<code>{{ selectedFile }}</code> · 共 <strong>{{ analysis.cycle_count }}</strong> 个采集周期 · 时间范围 {{ analysis.time_range.start }} → {{ analysis.time_range.end }}
        <span v-if="analysis.matched_versions && Object.keys(analysis.matched_versions).length" class="version-info">
          · 命中 {{ Object.keys(analysis.matched_versions).join(', ') }}
        </span>
      </div>

      <!-- 一、总体概览（不变） -->
      <section class="section">
        <h2>一、总体概览</h2>
        <div class="stat-grid">
          <div class="stat-card">
            <div class="stat-label">总进程数</div>
            <div class="stat-value">{{ overview?.total.toLocaleString() }}</div>
          </div>
          <div class="stat-card stat-oracle">
            <div class="stat-label">Oracle</div>
            <div class="stat-value">{{ overview?.oracle.toLocaleString() }}</div>
          </div>
          <div class="stat-card stat-grid">
            <div class="stat-label">Grid</div>
            <div class="stat-value">{{ overview?.grid.toLocaleString() }}</div>
          </div>
          <div class="stat-card stat-user">
            <div class="stat-label">用户</div>
            <div class="stat-value">{{ overview?.user.toLocaleString() }}</div>
          </div>
          <div class="stat-card stat-kernel">
            <div class="stat-label">Kernel 线程</div>
            <div class="stat-value">{{ overview?.kernel.toLocaleString() }}</div>
          </div>
          <div class="stat-card stat-system">
            <div class="stat-label">系统守护</div>
            <div class="stat-value">{{ overview?.system_daemon.toLocaleString() }}</div>
          </div>
          <div class="stat-card stat-script">
            <div class="stat-label">用户脚本</div>
            <div class="stat-value">{{ overview?.user_script.toLocaleString() }}</div>
          </div>
        </div>

        <h3 style="margin-top: 16px">按 USER 分布</h3>
        <table class="data-table">
          <thead>
            <tr>
              <th>USER</th>
              <th>进程数（去重 PID）</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in overview?.by_user" :key="u.user">
              <td><code class="user-tag">{{ u.user }}</code></td>
              <td>{{ u.process_count }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 二、核心指标时间线（按 USER 选择显示） -->
      <section class="section">
        <h2>二、核心指标时间线（按 USER 选择显示）</h2>
        <p class="section-desc">
          自动检测出所有 USER，点击下方按钮切换要显示的用户。
          选中用户的进程数趋势合并到下方 1 张大折线图（每用户 1 条线，可滚轮缩放）。
        </p>

        <!-- USER 选择器（chip 按钮组） -->
        <div v-if="userTrends && userTrends.users.length" class="user-selector-row">
          <div class="user-chips">
            <button
              v-for="u in userTrends.users"
              :key="u.user"
              class="user-chip"
              :class="{ active: isUserSelected(u.user) }"
              :title="`累计 ${fmtNum(u.total)} · 平均 ${u.avg} · 峰值 ${u.max}`"
              @click="toggleUser(u.user)"
            >
              <code class="user-chip-name">{{ u.user }}</code>
              <span class="user-chip-stat">×{{ fmtNum(u.total) }}</span>
            </button>
          </div>
          <div class="user-selector-actions">
            <button class="btn-mini" @click="selectAllUsers">全选</button>
            <button class="btn-mini" @click="selectNoneUsers">清空</button>
            <button class="btn-mini" @click="selectTopNUsers(3)">Top 3</button>
            <button class="btn-mini" @click="selectTopNUsers(5)">Top 5</button>
            <span class="selected-count">已选 {{ selectedUsers.length }} / {{ userTrends.users.length }}</span>
          </div>
        </div>

        <!-- 1 张大图：选中用户的进程数趋势 -->
        <div v-if="userTrends && userTrends.users.length" class="single-chart-wrap">
          <TimelineChart
            v-if="selectedUsers.length > 0"
            :title="`USER 进程数时序 · ${selectedUsers.length} 个用户`"
            :series="buildSelectedUserSeries()"
            :unit="`选中 ${selectedUsers.length} / 共 ${userTrends.users.length} 个用户`"
          />
          <div v-else class="empty">未选中任何用户，请在上方选择</div>
        </div>
      </section>

      <!-- 三、进程 WCHAN（NEW：等待的内核函数） -->
      <section class="section">
        <h2>三、进程 WCHAN（等待的内核函数）</h2>
        <p class="section-desc">
          <strong>重要程度 ★★★★★</strong>。WCHAN 字段是排查 IO 阻塞 / 锁竞争 / 网络等待的关键。
          本节将所有 wchan 归为 6 类（running / io / lock / net / timer / other），
          关注 io 和 lock 类别（卡住进程单独标红）。
        </p>
        <WchanAnalysis
          v-if="wchan"
          :wchan="wchan"
          :total-cycles="analysis.cycle_count"
        />
      </section>

      <!-- 四、TOP 进程（核心 8 字段：USER | PID | %CPU | RSS | STATE | WCHAN | STARTED | COMMAND） -->
      <section class="section">
        <h2>四、TOP 进程（核心 8 字段）</h2>
        <p class="section-desc">
          按你的字段说明建议的 8 核心列：<code>USER | PID | %CPU | RSS | STATE | WCHAN | STARTED | COMMAND</code>。
          数据来源：cpu_top ∪ mem_top（去重）。可点击列头排序，按 USER / STATE 过滤。
        </p>
        <CoreProcessTable
          :cpu-entries="cpuTop"
          :mem-entries="memTop"
        />
      </section>

      <!-- 五、USER 维度 -->
      <section class="section">
        <h2>五、USER 维度</h2>
        <h3>按 USER 聚合</h3>
        <table class="data-table">
          <thead>
            <tr>
              <th>USER</th>
              <th>进程数（去重 PID）</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in overview?.by_user" :key="u.user">
              <td><code class="user-tag">{{ u.user }}</code></td>
              <td>{{ u.process_count }}</td>
            </tr>
          </tbody>
        </table>

        <h3 style="margin-top: 24px">TOP 进程具体命令（按用户分组）</h3>
        <p class="section-desc">
          上方第五章节只显示 program + 8 字段（紧凑）；这里显示完整命令（路径 + 参数），按用户分组。
        </p>
        <TopCommandsByUser
          :cpu-entries="cpuTop"
          :mem-entries="memTop"
          :per-user-limit="5"
        />
      </section>

      <!-- 六、进程分类识别（COMMAND 字段：Oracle / Grid / 系统 / 脚本） -->
      <section class="section">
        <h2>六、进程分类识别（COMMAND 字段）</h2>

        <h3>Oracle 后台进程（最大并发 + 累计 PID）</h3>
        <div class="charts-grid stat-row">
          <div class="stat-card stat-oracle">
            <div class="stat-label">PX 峰值并发</div>
            <div class="stat-value">{{ oracle?.px_peak }}</div>
          </div>
          <div class="stat-card stat-oracle">
            <div class="stat-label">Job 峰值并发</div>
            <div class="stat-value">{{ oracle?.job_peak }}</div>
          </div>
        </div>
        <div v-if="oracleBgEntries.length === 0" class="empty">本样本未发现 Oracle 后台进程</div>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>类型</th>
              <th>最大并发</th>
              <th>累计不同 PID</th>
              <th>含义</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="[kind, maxCnt] in oracleBgEntries" :key="kind">
              <td><code class="oracle-tag">{{ kind }}</code></td>
              <td>{{ maxCnt }}</td>
              <td>{{ oracle?.distinct_pids[kind] ?? 0 }}</td>
              <td class="desc-cell">{{ ORACLE_DESC[kind] || '' }}</td>
            </tr>
          </tbody>
        </table>

        <h3 style="margin-top: 24px">Grid Infrastructure 进程</h3>
        <div v-if="gridKindEntries.length === 0" class="empty">本样本未发现 Grid 进程（可能是单实例数据库或非 RAC 环境）</div>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>类型</th>
              <th>最大并发</th>
              <th>累计不同 PID</th>
              <th>重启次数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="[kind, maxCnt] in gridKindEntries" :key="kind">
              <td><code class="grid-tag">{{ kind }}</code></td>
              <td>{{ maxCnt }}</td>
              <td>{{ grid?.distinct_pids[kind] ?? 0 }}</td>
              <td :class="{ high: (grid?.restart_count[kind] ?? 0) > 0 }">{{ grid?.restart_count[kind] ?? 0 }}</td>
            </tr>
          </tbody>
        </table>

        <h3 style="margin-top: 24px">Linux 系统进程（kworker / jbd2 / multipathd / systemd 等）</h3>
        <div v-if="systemKindEntries.length === 0" class="empty">本样本未发现 kworker/jbd2/multipathd/systemd 等系统进程</div>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>类型</th>
              <th>平均数</th>
              <th>峰值</th>
              <th>出现 cycle 数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="[kind, peakCnt] in systemKindEntries" :key="kind">
              <td><code class="system-tag">{{ kind }}</code></td>
              <td>{{ system?.kind_avg[kind] ?? 0 }}</td>
              <td>{{ peakCnt }}</td>
              <td>{{ system?.kind_cycles[kind] ?? 0 }} / {{ system?.cycle_count ?? 0 }}</td>
            </tr>
          </tbody>
        </table>

        <h3 style="margin-top: 24px">用户脚本（raid-check / rman / expdp / tar / gzip / rsync 等）</h3>
        <div v-if="userScripts.length === 0" class="empty">本样本未发现 raid-check / rman / expdp / impdp / tar / gzip / rsync / scp / backup.sh 等用户脚本</div>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>脚本名</th>
              <th>执行次数</th>
              <th>最大 CPU%</th>
              <th>最大 RSS</th>
              <th>开始 → 结束</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in userScripts" :key="s.name">
              <td><code class="script-tag">{{ s.name }}</code></td>
              <td>{{ s.run_count }}</td>
              <td :class="{ high: s.max_cpu >= 50 }">{{ s.max_cpu.toFixed(1) }}%</td>
              <td>{{ formatKB(s.max_rss_kb) }}</td>
              <td class="time-cell">{{ s.first_seen }} → {{ s.last_seen }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 七、生命周期（STARTED 字段） -->
      <section class="section">
        <h2>七、生命周期（STARTED 字段）</h2>
        <p class="section-desc">
          跟踪 Oracle / Grid / Script / System 四类重要进程的运行时长，按 duration 降序排列。
          "频率"指进程出现在多少个 cycle 中（进度条 = cycles_seen / 总 cycle 数）。
        </p>
        <ProgramRuntimeTable :lifecycle="lifecycle" :total-cycles="analysis.cycle_count" />
      </section>

      <!-- 八、结论与建议 -->
      <section class="section">
        <h2>八、结论与建议</h2>
        <p class="section-desc">本节以 Markdown 报告形式提供，便于发给团队或归档。点击右上角"导出 Markdown 报告"按钮下载。</p>
        <div class="conclusion-hints">
          <ul>
            <li>Oracle 后台进程并发稳定（pmon/lgwr/dbw 各 {{ oracle?.background_counts.pmon }}/{{ oracle?.background_counts.lgwr }}/{{ oracle?.background_counts.dbw }}）。</li>
            <li v-if="(oracle?.px_peak ?? 0) > 0">采样期内 PX 并行峰值 {{ oracle?.px_peak }}（并行查询活跃）。</li>
            <li v-if="(oracle?.job_peak ?? 0) > 0">采样期内 Job 队列峰值 {{ oracle?.job_peak }}。</li>
            <li v-if="(grid?.restart_count?.asm_pmon ?? 0) > 0">Grid asm_pmon 重启 {{ grid?.restart_count?.asm_pmon }} 次，建议检查 ASM 状态。</li>
            <li v-if="(grid?.restart_count?.cha ?? 0) > 0">Grid CHA 重启 {{ grid?.restart_count?.cha }} 次。</li>
            <li v-if="userScripts.length > 0">检测到 {{ userScripts.length }} 类用户脚本执行：{{ userScripts.map(s => s.name).join('、') }}。</li>
            <li v-if="(cpuTop[0]?.cpu_pct_max ?? 0) > 100">CPU TOP 1（{{ cpuTop[0]?.command.slice(0, 30) }}...）单核峰值 {{ cpuTop[0]?.cpu_pct_max }}%，需关注。</li>
            <li v-if="(memTop[0]?.rss_max_kb ?? 0) > 2 * 1024 * 1024">Memory TOP 1（{{ memTop[0]?.command }}）RSS 峰值 {{ formatKB(memTop[0]?.rss_max_kb ?? 0) }}，超过 2G。</li>
            <li v-if="(state?.zombie_pids?.length ?? 0) > 0">**发现 {{ state?.zombie_pids?.length }} 个持续 Zombie 进程**，检查父进程未回收原因。</li>
            <li v-if="(state?.long_d_pids?.length ?? 0) > 0">**发现 {{ state?.long_d_pids?.length }} 个持续 D 状态进程**（I/O 阻塞），结合 iostat 看磁盘。</li>
            <li v-if="(wchan?.stuck_pids?.length ?? 0) > 0">**发现 {{ wchan?.stuck_pids?.length }} 个进程持续在 IO / Lock 等待**（≥ 5 cycle），结合 iostat 看磁盘 util/await。</li>
          </ul>
        </div>
      </section>
    </template>

    <!-- 弹窗 -->
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

<script lang="ts">
// 单独 <script> 块定义 Oracle 后台进程含义（不在 setup 里以避免每次重渲重建）
const ORACLE_DESC: Record<string, string> = {
  pmon: 'Process Monitor（进程监控）',
  lgwr: 'Log Writer（日志写入）',
  dbw: 'Database Writer（数据块写入，dbw0..dbwe 多个）',
  ckpt: 'Checkpoint（检查点）',
  mman: 'Memory Manager（内存管理，含 mmnl）',
  mmon: 'Manageability Monitor（可管理性监控）',
  smon: 'System Monitor（系统监控）',
  reco: 'Recoverer（恢复器）',
  qmn: 'Queue Monitor（队列监控）',
  vktm: 'Virtual Keeper of Time（虚拟时间维护）',
  lmon: 'Lock Monitor（锁监控，RAC）',
  lmd: 'Lock Manager Daemon（锁管理守护，RAC）',
  lck: 'Lock Process（锁进程，RAC）',
  rms: 'RAC Management Service（RAC 管理）',
  rvwr: 'Recovery Writer（恢复写入）',
  arc: 'Archiver（归档，arc0..arc9）',
  tt: 'Temp Table（临时表，tt00..tt15）',
  dia: 'Diagnostic（诊断，dia0/dia1）',
  m: 'MMON Slave（MMON 从进程 m000..）',
  s: 'Shared Server（共享服务器 s000..）',
  n: 'Connection Broker（连接代理 n000..）',
  px: 'Parallel Execution（并行执行 p000..p999）',
  pr: 'Parallel Recovery（并行恢复 pr00..pr99）',
  job: 'Job Slave（CJQ0 + J000..J999）',
  other: '其它 ora_* 进程',
}
export default {}
</script>

<style scoped>
.ps-view {
  max-width: 1400px;
  margin: 0 auto;
  padding: 16px;
}

.header {
  margin-bottom: 16px;
}
.version-hint {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 12px;
  color: #888;
}
.version-hint-label {
  margin-right: 4px;
}
.version-tag {
  display: inline-block;
  padding: 1px 8px;
  border: 1px solid #ddd;
  border-radius: 10px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  color: #555;
  background: #fafafa;
  cursor: help;
  white-space: nowrap;
}

.section {
  margin-bottom: 32px;
}
.section h2 {
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 12px;
  padding-bottom: 6px;
  border-bottom: 2px solid #e5e7eb;
}
.section h3 {
  font-size: 14px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 8px;
  margin-top: 16px;
}
.section-desc {
  color: #6b7280;
  font-size: 13px;
  margin-bottom: 8px;
}

.path-row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.path-input {
  flex: 1;
  min-width: 280px;
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 14px;
  font-family: monospace;
}
.btn {
  padding: 8px 16px;
  border: 1px solid #ddd;
  background: #f5f5f5;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  white-space: nowrap;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-primary {
  background: #2563eb;
  color: white;
  border-color: #2563eb;
}
.btn-primary:disabled {
  background: #93c5fd;
  border-color: #93c5fd;
}
.btn-success {
  background: #16a34a;
  color: white;
  border-color: #16a34a;
  cursor: pointer;
  display: inline-block;
}
.btn-success:hover:not(.disabled) {
  background: #15803d;
  border-color: #15803d;
}
.btn-success.disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background: #86efac;
  border-color: #86efac;
}
.btn-export {
  background: #7c3aed;
  color: white;
  border-color: #7c3aed;
}
.btn-export:hover:not(:disabled) {
  background: #6d28d9;
  border-color: #6d28d9;
}
.btn-export:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.current-dir {
  margin-top: 6px;
  color: #555;
  font-size: 12px;
}
.current-dir code {
  background: #f0f4ff;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  color: #1e3a8a;
  word-break: break-all;
}
.loading {
  margin-top: 8px;
  color: #2563eb;
  font-size: 13px;
}
.error {
  margin-top: 8px;
  color: #dc2626;
  font-size: 13px;
}
.result-info {
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 6px;
  padding: 10px 14px;
  font-size: 13px;
  color: #0369a1;
  margin-bottom: 20px;
}
.result-info code {
  background: #e0f2fe;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  color: #075985;
}
.result-info .version-info {
  color: #6b7280;
  margin-left: 6px;
  font-size: 12px;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}
.stat-row {
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  margin-bottom: 12px;
  margin-top: 0;
}
.stat-card {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px 16px;
}
.stat-card.stat-oracle { background: #fef2f2; border-color: #fecaca; }
.stat-card.stat-grid { background: #f0fdf4; border-color: #bbf7d0; }
.stat-card.stat-user { background: #eff6ff; border-color: #bfdbfe; }
.stat-card.stat-kernel { background: #f9fafb; }
.stat-card.stat-system { background: #f9fafb; }
.stat-card.stat-script { background: #faf5ff; border-color: #e9d5ff; }
.stat-label {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 4px;
}
.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: #1f2937;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}

/* iostat 风格的 charts 网格 */
.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 12px;
}

/* ─── USER 选择器（chip 按钮组） ─── */
.user-selector-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 14px;
  padding: 10px 12px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}
.user-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.user-chip {
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
.user-chip:hover {
  border-color: #93c5fd;
  background: #eff6ff;
}
.user-chip.active {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
}
.user-chip.active .user-chip-stat {
  color: #dbeafe;
}
.user-chip-name {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 12px;
  font-weight: 600;
}
.user-chip-stat {
  font-size: 10px;
  color: #6b7280;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
.user-selector-actions {
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

/* 单图全宽容器（覆盖 TimelineChart 默认 300px） */
.single-chart-wrap {
  width: 100%;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 8px;
  min-height: 360px;
}
.single-chart-wrap :deep(.timeline-chart) {
  height: 360px !important;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  overflow: hidden;
}
.data-table th,
.data-table td {
  text-align: left;
  padding: 6px 10px;
  border-bottom: 1px solid #f3f4f6;
}
.data-table th {
  color: #6b7280;
  font-weight: 600;
  background: #f9fafb;
  font-size: 12px;
}
.data-table tbody tr:last-child td {
  border-bottom: none;
}
.data-table .high {
  color: #dc2626;
  font-weight: 600;
}
.data-table .time-cell {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  color: #4b5563;
}
.data-table .desc-cell {
  color: #6b7280;
  font-size: 12px;
}
.user-tag {
  background: #eff6ff;
  color: #1e3a8a;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
}
.oracle-tag {
  background: #fef2f2;
  color: #b91c1c;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  font-weight: 600;
}
.grid-tag {
  background: #f0fdf4;
  color: #15803d;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  font-weight: 600;
}
.system-tag {
  background: #f3f4f6;
  color: #374151;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
}
.script-tag {
  background: #faf5ff;
  color: #6d28d9;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
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

.conclusion-hints {
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 6px;
  padding: 12px 16px;
  font-size: 13px;
  color: #78350f;
}
.conclusion-hints ul {
  margin: 0;
  padding-left: 20px;
}
.conclusion-hints li {
  margin-bottom: 4px;
  line-height: 1.6;
}
</style>
