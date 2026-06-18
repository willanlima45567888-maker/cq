/**
 * OSW-View · ps 工具专用 API
 */

import { ApiError } from './common'

const BASE = '/api'

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const body = (await res.json().catch(() => ({ detail: res.statusText }))) as {
      detail: unknown
    }
    throw new ApiError(
      res.status,
      body.detail,
      typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail),
    )
  }
  return res.json()
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path, { method: 'GET' })
  if (!res.ok) {
    const body = (await res.json().catch(() => ({ detail: res.statusText }))) as {
      detail: unknown
    }
    throw new ApiError(
      res.status,
      body.detail,
      typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail),
    )
  }
  return res.json()
}

export interface ScanResponse {
  files: string[]
  scanned_dir: string
  cleaned_count: number
  tool: string
}

export interface PsProcess {
  user: string
  pid: number
  ppid: number
  pri: number
  cpu_pct: number
  mem_pct: number
  vsz: number
  rss: number
  wchan: string
  s: string
  started: string
  time: string
  command: string
}

export interface PsCycle {
  timestamp: string
  processes: PsProcess[]
}

export interface ParseResponse {
  cycles_count: number
  devices: string[]
  metrics: string[]
  cpu_metrics: string[]
  data: {
    cycles: PsCycle[]
  }
  matched_versions: Record<string, string[]>
  truncated: boolean
  max_cycles: number
}

/** 后端 /api/ps/versions 返回的版本项 */
export interface PsVersionInfo {
  version: string
  display_name: string
  captured_at: string
  added_by: string
  notes: string
  banner: string
  active?: boolean
}

/** 后端 422 unknown_format 的 detail（ps 版） */
export interface UnknownFormatDetail {
  error: 'unknown_format'
  banner: string | null
  header_columns: string[] | null
  pending_path: string
}

// ─── /api/ps/analyze 响应类型（Oracle/RAC 故障排查专用）────────────

export interface PsOverview {
  total: number
  oracle: number
  grid: number
  kernel: number
  user: number
  system_daemon: number
  user_script: number
  by_user: { user: string; process_count: number }[]
}

export interface PsTrends {
  timestamps: string[]
  total: number[]
  oracle: number[]
  grid: number[]
  kernel: number[]
  user: number[]
  system_daemon: number[]
  user_script: number[]
  px: number[]
  job: number[]
}

export interface PsCpuTopEntry {
  command: string
  user: string
  pid: number
  cpu_pct_max: number
  cpu_pct_avg: number
  cycles_seen: number
  first_seen: string
  last_seen: string
  // 补全字段（来自 _enrich_top_entries）
  rss_max_kb: number
  state: string  // 主导状态
  wchan: string  // 主导 wchan
}

export interface PsMemTopEntry {
  command: string
  user: string
  pid: number
  rss_max_kb: number
  rss_avg_kb: number
  vsz_max_kb: number
  cycles_seen: number
  first_seen: string
  last_seen: string
  // 补全字段
  cpu_pct_max: number
  cpu_pct_avg: number
  state: string
  wchan: string
}

export interface PsOracleAnalysis {
  background_counts: Record<string, number>
  background_by_cycle: Array<Record<string, number> & { timestamp: string }>
  px_peak: number
  job_peak: number
  distinct_pids: Record<string, number>
}

export interface PsGridAnalysis {
  kind_counts: Record<string, number>
  kind_by_cycle: Array<Record<string, number> & { timestamp: string }>
  distinct_pids: Record<string, number>
  restart_count: Record<string, number>
}

export interface PsSystemAnalysis {
  kind_avg: Record<string, number>
  kind_peak: Record<string, number>
  kind_cycles: Record<string, number>
  cycle_count: number
}

export interface PsUserScriptRun {
  pid: number
  first_seen: string
  last_seen: string
  max_cpu: number
  max_rss_kb: number
  command_sample: string
}

export interface PsUserScript {
  name: string
  run_count: number
  first_seen: string
  last_seen: string
  max_cpu: number
  max_rss_kb: number
  runs: PsUserScriptRun[]
}

export interface PsStateZombiePid {
  pid: number
  user: string
  command: string
  first_seen: string
  last_seen: string
  cycles_z: number
}

export interface PsStateLongDPid {
  pid: number
  user: string
  command: string
  first_seen: string
  last_seen: string
  cycles_d: number
}

export interface PsStateAnalysis {
  by_cycle: Array<Record<string, number> & { timestamp: string }>
  total_by_state: Record<string, number>
  current: Record<string, number>
  max_z: number
  max_d: number
  max_r: number
  zombie_pids: PsStateZombiePid[]
  long_d_pids: PsStateLongDPid[]
  state_order: string[]
  state_legend: Record<string, string>
}

export interface PsWchanTopEntry {
  wchan: string
  category: string
  count: number
}

export interface PsWchanStuckPid {
  pid: number
  user: string
  command: string
  wchan: string
  category: string
  cycles: number
  first_seen: string
  last_seen: string
}

export interface PsWchanAnalysis {
  by_cycle: Array<Record<string, number> & { timestamp: string }>
  category_total: Record<string, number>
  category_max: Record<string, number>
  top_wchans: PsWchanTopEntry[]
  stuck_pids: PsWchanStuckPid[]
  category_order: string[]
  category_legend: Record<string, string>
}

export interface PsUserTrendEntry {
  user: string
  total: number
  avg: number
  max: number
}

export interface PsUserTrends {
  users: PsUserTrendEntry[]
  by_cycle: Array<Record<string, number> & { timestamp: string }>
  top_n: number
}

export interface PsLifecyclePid {
  pid: number
  first_seen: string
  last_seen: string
}

export interface PsLifecycleEntry {
  name: string
  category: 'oracle' | 'grid' | 'system' | 'script'
  first_seen: string
  last_seen: string
  pid_count: number
  duration_seconds: number
  cycles_seen: number
  frequency_pct: number
  pids: PsLifecyclePid[]
}

export interface PsAnalysisResponse {
  cycle_count: number
  matched_versions: Record<string, string[]>
  time_range: { start: string; end: string }
  state: PsStateAnalysis
  wchan: PsWchanAnalysis
  user_trends: PsUserTrends
  overview: PsOverview
  trends: PsTrends
  cpu_top: PsCpuTopEntry[]
  mem_top: PsMemTopEntry[]
  oracle: PsOracleAnalysis
  grid: PsGridAnalysis
  system: PsSystemAnalysis
  user_scripts: PsUserScript[]
  lifecycle: PsLifecycleEntry[]
}

// ─── 旧的 /api/parse/summary 响应类型（保留兼容）────────────

export interface PsUserSummary {
  user: string
  cycle_count: number
  process_count_avg: number
  process_count_max: number
  cpu_pct_avg: number
  cpu_pct_max: number
  mem_pct_avg: number
  mem_pct_max: number
  rss_total_kb_avg: number
}

export interface PsCommandSummary {
  command: string
  occurrence_count: number
  cycle_count: number
  cpu_pct_avg: number
  mem_pct_avg: number
  rss_avg_kb: number
}

export interface PsSummaryResponse {
  cycle_count: number
  total_processes: number
  by_user: PsUserSummary[]
  by_command: PsCommandSummary[]
  matched_versions: Record<string, string[]>
}

export const psApi = {
  /** 扫描目录，返回 ps 格式文件列表（.dat / .dat.gz） */
  scan: (path: string, tool: string = 'ps') => post<ScanResponse>('/scan', { path, tool }),

  /** 解析选中的文件（按 cycle 详情） */
  parse: (dirPath: string, files: string[], maxCycles: number = 50) =>
    post<ParseResponse>('/parse', {
      dir_path: dirPath,
      files,
      parser_type: 'ps',
      max_cycles: maxCycles,
    }),

  /** 旧的通用汇总（保留兼容） */
  summary: (dirPath: string, files: string[]) =>
    post<PsSummaryResponse>('/parse/summary', {
      dir_path: dirPath,
      files,
      parser_type: 'ps',
    }),

  /**
   * ps 工具深度分析（Oracle/RAC 故障排查专用）
   * - 首次 ~36s（parse 17s + analyze 20s），后续 cache 命中 ~40ms
   * - 响应 ~620KB
   */
  analyze: (dirPath: string, file: string) =>
    post<PsAnalysisResponse>('/ps/analyze', {
      dir_path: dirPath,
      files: [file],
      parser_type: 'ps',
      max_cycles: 50,
    }),

  /** 列出已注册的 ps 格式版本 */
  listPsVersions: () =>
    get<{ versions: PsVersionInfo[] }>('/ps/versions'),
}
