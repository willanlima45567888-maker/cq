<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ApiError, commonApi } from '../api/common'
import { iostatApi, type ParseResponse, type IostatVersionInfo, type UnknownFormatDetail } from '../api/iostat'
// 跨工具通用组件
import FileSelector from '../components/FileSelector.vue'
import TimelineChart from '../components/TimelineChart.vue'
import UnknownFormatDialog from '../components/UnknownFormatDialog.vue'
import UploadResultDialog from '../components/UploadResultDialog.vue'
import MatchedVersionDialog from '../components/MatchedVersionDialog.vue'
// iostat 专用组件
import StatsOverview from './iostat-components/StatsOverview.vue'

// 状态
const dirPath = ref('')
const files = ref<string[]>([])
const selectedFiles = ref<string[]>([])
const parsedData = ref<ParseResponse | null>(null)
const loading = ref(false)
const error = ref('')

// 未识别格式弹窗状态
const unknownFormatInfo = ref<UnknownFormatDetail | null>(null)

// 命中版本弹窗状态（每次解析成功后都弹）
const matchedVersions = ref<Record<string, string[]> | null>(null)

// 上传结果弹窗状态
interface UploadedItem { original: string; saved_as: string; path: string }
interface FailedItem { filename: string; reason: string }
const uploadResult = ref<{ uploaded: UploadedItem[]; failed: FailedItem[] } | null>(null)

// 已注册版本（顶部小提示 + 弹窗里展示友好名用）
// 过滤掉 active=false 的版本（如 v0003 这种 fingerprint 跟 v0002 一样的占位版）
const supportedVersions = ref<IostatVersionInfo[]>([])
onMounted(async () => {
  try {
    const res = await iostatApi.listIostatVersions()
    supportedVersions.value = res.versions.filter((v) => v.active !== false)
  } catch {
    // 静默失败：版本列表是辅助信息
  }
})

// version_id -> display_name 映射（弹窗里展示友好名）
const versionDisplayNames = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const v of supportedVersions.value) {
    out[v.version] = v.display_name
  }
  return out
})

// 文件扫描
async function scan() {
  if (!dirPath.value.trim()) return
  loading.value = true
  error.value = ''
  unknownFormatInfo.value = null
  matchedVersions.value = null
  try {
    const res = await iostatApi.scan(dirPath.value.trim())
    files.value = res.files
    selectedFiles.value = []
    parsedData.value = null
  } catch (e: any) {
    error.value = e?.message ?? String(e)
  } finally {
    loading.value = false
  }
}

// 扫描默认的上传目录（oswupdownload_file/）
// 后端会顺手清理 mtime 超过保留天数的过期文件
async function scanUploadDir() {
  loading.value = true
  error.value = ''
  unknownFormatInfo.value = null
  matchedVersions.value = null
  try {
    const res = await iostatApi.scan('', 'iostat')  // 空 path → 后端走 iostat 子目录
    dirPath.value = res.scanned_dir  // 把实际扫描的目录回填到输入框
    files.value = res.files
    selectedFiles.value = []
    parsedData.value = null
    if (res.cleaned_count > 0) {
      console.info(`[cleanup] 已清理 ${res.cleaned_count} 个超过 7 天的过期文件`)
    }
  } catch (e: any) {
    error.value = e?.message ?? String(e)
  } finally {
    loading.value = false
  }
}

// 上传文件到后端 oswupdownload_file/，上传后自动 scan 刷新列表
async function onUpload(e: Event) {
  const target = e.target as HTMLInputElement
  if (!target.files || target.files.length === 0) return
  loading.value = true
  error.value = ''
  try {
    const res = await commonApi.uploadFiles(target.files, 'iostat')
    console.info(`[upload] 成功 ${res.uploaded_count} 个，失败 ${res.failed_count} 个`)
    // 弹窗告知完整结果（包含重命名、失败原因、绝对路径）
    if (res.uploaded_count > 0 || res.failed_count > 0) {
      uploadResult.value = { uploaded: res.uploaded, failed: res.failed }
    }
    // 上传后自动 scan 一次，让新文件出现在列表里
    if (res.uploaded_count > 0) {
      await scanUploadDir()
    }
  } catch (e: any) {
    error.value = e?.message ?? String(e)
  } finally {
    target.value = ''  // 清空以便能再次上传同名文件
    loading.value = false
  }
}

// 解析选中文件
async function parse() {
  if (!selectedFiles.value.length) return
  loading.value = true
  error.value = ''
  unknownFormatInfo.value = null
  matchedVersions.value = null
  try {
    parsedData.value = await iostatApi.parse(dirPath.value, selectedFiles.value)
    // 每次解析成功都弹命中提示
    if (parsedData.value.matched_versions &&
        Object.keys(parsedData.value.matched_versions).length > 0) {
      matchedVersions.value = parsedData.value.matched_versions
    }
  } catch (e: any) {
    // 422 unknown_format → 弹 modal
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

// 设备切换
const selectedDevices = ref<string[]>([])

function toggleDevice(dev: string) {
  const idx = selectedDevices.value.indexOf(dev)
  if (idx >= 0) {
    selectedDevices.value.splice(idx, 1)
  } else {
    selectedDevices.value.push(dev)
  }
}

function isDeviceSelected(dev: string) {
  return selectedDevices.value.includes(dev)
}

// 指标列表（去掉 device 字段）
const metrics = computed(() => parsedData.value?.metrics || [])
const cpuMetrics = computed(() => parsedData.value?.cpu_metrics || [])

// 时间线数据：每个指标一张图，每个设备一条线
interface SeriesData {
  name: string
  data: [string, number][]
}

function buildDeviceSeries(metric: string, deviceFilter: string[]): SeriesData[] {
  if (!parsedData.value) return []
  const cycles = parsedData.value.data.cycles
  return deviceFilter.map(devName => {
    const data: [string, number][] = []
    for (const cyc of cycles) {
      const dev = cyc.devices.find((d: any) => d.device === devName)
      if (dev && metric in dev && dev[metric] !== null) {
        data.push([cyc.timestamp, dev[metric] as number])
      }
    }
    return { name: devName, data }
  }).filter(s => s.data.length > 0)
}

function buildCpuSeries(metric: string): SeriesData[] {
  if (!parsedData.value) return []
  const cycles = parsedData.value.data.cycles
  const data: [string, number][] = []
  for (const cyc of cycles) {
    if (cyc.cpu && metric in cyc.cpu) {
      data.push([cyc.timestamp, cyc.cpu[metric] as number])
    }
  }
  return [{ name: metric, data }]
}

// 指标 → 单位映射（中文描述放括号内）
const METRIC_UNITS: Record<string, string> = {
  util: '% (磁盘利用率)',
  r_s: 'ops/s (读操作率)',
  w_s: 'ops/s (写操作率)',
  rrqm_s: 'ops/s (读请求合并率)',
  wrqm_s: 'ops/s (写请求合并率)',
  rkb_s: 'KB/s (读吞吐量)',
  wkb_s: 'KB/s (写吞吐量)',
  avgrq_sz: 'sectors (平均请求大小)',
  avgqu_sz: 'requests (平均队列长度)',
  await: 'ms (平均响应时间)',
  r_await: 'ms (读平均响应时间)',
  w_await: 'ms (写平均响应时间)',
  svctm: 'ms (平均服务时间)',
  '%user': '% (用户CPU)',
  '%nice': '% (nice CPU)',
  '%system': '% (系统CPU)',
  '%iowait': '% (I/O等待)',
  '%steal': '% (steal)',
  '%idle': '% (空闲)',
}
</script>

<template>
  <div class="iostat-view">
    <header class="header">
      <div v-if="supportedVersions.length" class="version-hint">
        <span class="version-hint-label">已支持 {{ supportedVersions.length }} 个 iostat 格式版本：</span>
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
          placeholder="输入 OSW 数据目录路径（留空则扫描上传目录 oswupdownload_file/），如 /data/osw/oswiostat/"
          @keyup.enter="scan"
        />
        <button class="btn" :disabled="loading" @click="scan">刷新</button>
        <button class="btn" :disabled="loading" @click="scanUploadDir" title="扫描项目根下的 oswupdownload_file/，自动清理超过 7 天的文件">
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
          :disabled="loading || !selectedFiles.length"
          @click="parse"
        >
          解析
        </button>
      </div>
      <div v-if="loading" class="loading">加载中...</div>
      <div v-if="error" class="error">{{ error }}</div>
      <div v-if="dirPath" class="current-dir">
        当前目录：<code>{{ dirPath }}</code>
      </div>
    </section>

    <!-- 文件列表 -->
    <section v-if="files.length" class="section">
      <h2>文件列表（已选 {{ selectedFiles.length }} 个）</h2>
      <FileSelector
        :files="files"
        :selected="selectedFiles"
        @toggle="(f) => { const i = selectedFiles.indexOf(f); if(i>=0) selectedFiles.splice(i,1); else selectedFiles.push(f) }"
        @select-all="selectedFiles = [...files]"
        @deselect-all="selectedFiles = []"
      />
    </section>

    <!-- 解析结果 -->
    <template v-if="parsedData">
      <div class="result-info">
        共 {{ parsedData.cycles_count }} 个采集周期 · {{ parsedData.devices.length }} 个设备 · {{ parsedData.metrics.length }} 个设备指标
      </div>

      <!-- 设备选择 -->
      <section class="section">
        <h2>设备选择</h2>
        <div class="device-list">
          <button
            v-for="dev in parsedData.devices"
            :key="dev"
            class="device-btn"
            :class="{ active: isDeviceSelected(dev) }"
            @click="toggleDevice(dev)"
          >
            {{ dev }}
          </button>
        </div>
      </section>

      <!-- CPU 时间线 -->
      <section v-if="cpuMetrics.length" class="section">
        <h2>CPU 指标</h2>
        <div class="charts-grid">
          <TimelineChart
            v-for="metric in cpuMetrics"
            :key="`cpu-${metric}`"
            :title="`${metric} (CPU)`"
            :series="buildCpuSeries(metric)"
            :unit="METRIC_UNITS[metric] || ''"
          />
        </div>
      </section>

      <!-- 设备指标时间线 -->
      <section v-if="selectedDevices.length" class="section">
        <h2>设备指标时间线</h2>
        <div class="charts-grid">
          <TimelineChart
            v-for="metric in metrics"
            :key="`dev-${metric}`"
            :title="metric"
            :series="buildDeviceSeries(metric, selectedDevices)"
            :unit="METRIC_UNITS[metric] || ''"
          />
        </div>
      </section>

      <!-- 统计概览 -->
      <section v-if="selectedDevices.length" class="section">
        <StatsOverview
          :data="parsedData"
          :selected-devices="selectedDevices"
        />
      </section>
    </template>

    <!-- 未识别格式弹窗 -->
    <UnknownFormatDialog
      v-if="unknownFormatInfo"
      :banner="unknownFormatInfo.banner"
      :header-columns="unknownFormatInfo.header_columns"
      :pending-path="unknownFormatInfo.pending_path"
      @close="unknownFormatInfo = null"
    />

    <!-- 命中版本弹窗（每次解析都弹） -->
    <MatchedVersionDialog
      v-if="matchedVersions"
      :matched-versions="matchedVersions"
      :version-display-names="versionDisplayNames"
      :total-files="selectedFiles.length"
      @close="matchedVersions = null"
    />

    <!-- 上传结果弹窗（每次上传都弹） -->
    <UploadResultDialog
      v-if="uploadResult"
      :uploaded="uploadResult.uploaded"
      :failed="uploadResult.failed"
      @close="uploadResult = null"
    />
  </div>
</template>

<style scoped>
.iostat-view {
  max-width: 1400px;
  margin: 0 auto;
  padding: 16px;
}
.header {
  margin-bottom: 16px;
}
.section {
  margin-bottom: 20px;
}
.section h2 {
  font-size: 14px;
  font-weight: 600;
  color: #555;
  margin-bottom: 8px;
}
.path-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.path-input {
  flex: 1;
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
}
.version-hint {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
  color: #888;
  font-size: 12px;
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
  transition: all 0.15s;
}
.version-tag:hover {
  background: #eef2ff;
  border-color: #93c5fd;
  color: #1e3a8a;
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
.loading {
  margin-top: 8px;
  color: #666;
  font-size: 13px;
}
.error {
  margin-top: 8px;
  color: #dc2626;
  font-size: 13px;
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
.device-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.device-btn {
  padding: 4px 12px;
  border: 1px solid #ddd;
  background: #f5f5f5;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  font-family: monospace;
  transition: all 0.15s;
}
.device-btn.active {
  background: #2563eb;
  color: white;
  border-color: #2563eb;
}
.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(600px, 1fr));
  gap: 12px;
}
.result-info {
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 13px;
  color: #0369a1;
  margin-bottom: 16px;
}
</style>
