/**
 * OSW-View · top 工具专用 API
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

export interface TopVersionInfo {
  version: string
  display_name: string
  captured_at: string
  added_by: string
  notes: string
  banner: string
  active?: boolean
}

export interface UnknownFormatDetail {
  error: 'unknown_format'
  banner: string | null
  header_columns: string[] | null
  pending_path: string
}

// ─── /api/top/analyze 响应类型 ───────────────────────────

export interface TopOverview {
  cycle_count: number
  total_procs: number
  load_1m_max: number
  cpu_us_max: number
  cpu_wa_max: number
  total: number
  oracle: number
  grid: number
  kernel: number
  user: number
  system_daemon: number
  user_script: number
  by_user: { user: string; process_count: number }[]
}

export interface TopSystemTrends {
  timestamps: string[]
  load_1m: number[]
  load_5m: number[]
  load_15m: number[]
  tasks_total: number[]
  tasks_running: number[]
  tasks_sleeping: number[]
  tasks_stopped: number[]
  tasks_zombie: number[]
  cpu_us: number[]
  cpu_sy: number[]
  cpu_ni: number[]
  cpu_id: number[]
  cpu_wa: number[]
  cpu_hi: number[]
  cpu_si: number[]
  cpu_st: number[]
  mem_total: number[]
  mem_used: number[]
  mem_free: number[]
  mem_buff: number[]
  mem_pct: number[]
  swap_total: number[]
  swap_used: number[]
  avail_mem: number[]
}

export interface TopCpuTopEntry {
  command: string
  user: string
  pid: number
  cpu_pct_max: number
  cpu_pct_avg: number
  cycles_seen: number
  first_seen: string
  last_seen: string
  res_kb_max: number
  state: string
  mem_pct_max: number
  mem_pct_avg: number
  /** 该程序出现在 cpu_pct 每个 cycle TOP 5 之前的次数 */
  top5_count: number
}

export interface TopMemTopEntry {
  command: string
  user: string
  pid: number
  res_kb_max: number
  res_kb_avg: number
  virt_kb_max: number
  cycles_seen: number
  cpu_pct_max: number
  cpu_pct_avg: number
  mem_pct_max: number
  mem_pct_avg: number
  first_seen: string
  last_seen: string
  state: string
  /** 该程序出现在 mem_pct 每个 cycle TOP 5 之前的次数 */
  top5_count: number
}

export interface TopProcessCategories {
  timestamps: string[]
  total: number[]
  oracle: number[]
  grid: number[]
  kernel: number[]
  user: number[]
  system_daemon: number[]
  user_script: number[]
}

export interface TopUserDistributionEntry {
  user: string
  total: number
  avg: number
  max: number
}

export interface TopUserDistribution {
  users: TopUserDistributionEntry[]
  by_cycle: Array<Record<string, number> & { timestamp: string }>
  top_n: number
}

export interface TopStateLongDPid {
  pid: number
  user: string
  command: string
  first_seen: string
  last_seen: string
  cycles_d: number
}

export interface TopStateZombiePid {
  pid: number
  user: string
  command: string
  first_seen: string
  last_seen: string
  cycles_z: number
}

export interface TopStateTrends {
  by_cycle: Array<Record<string, number> & { timestamp: string }>
  total_by_state: Record<string, number>
  current: Record<string, number>
  max_d: number
  max_z: number
  max_r: number
  long_d_pids: TopStateLongDPid[]
  zombie_pids: TopStateZombiePid[]
  state_order: string[]
  state_legend: Record<string, string>
}

export interface TopProgramCpuTimelineProgram {
  command: string
  total_cpu: number
  cycles_seen: number
  avg_cpu: number
}

export interface TopProgramCpuTimeline {
  /** Top N 按 command 聚合的 CPU% 累加器（跨用户/PID 求和，反映"程序占用了多少核"） */
  programs: TopProgramCpuTimelineProgram[]
  by_cycle: Array<Record<string, number> & { timestamp: string }>
  top_n: number
}

// ─── /api/top/snapshot 响应类型 ──────────────────────

export interface TopSnapshotProcess {
  pid: number
  user: string
  pr: number
  ni: number
  virt_kb: number
  res_kb: number
  shr_kb: number
  s: string
  cpu_pct: number
  mem_pct: number
  time_str: string
  command: string
}

export interface TopSnapshotResponse {
  cycle_index: number
  total_cycles: number
  timestamp: string
  summary: Record<string, number | string>
  processes: TopSnapshotProcess[]
  matched_versions: Record<string, string[]>
}

// ─── /api/top/pid_history 响应类型 ────────────────────

export interface TopPidHistoryPoint {
  cycle_index: number
  timestamp: string
  cpu_pct: number
  mem_pct: number
  res_kb: number
  virt_kb: number
  shr_kb: number
  s: string
  pr: number
  ni: number
  time_str: string
  user: string
  command: string
}

export interface TopPidHistoryResponse {
  pid: number
  command: string
  user: string
  first_seen_cycle: number
  last_seen_cycle: number
  first_seen_ts: string
  last_seen_ts: string
  cycles_seen: number
  total_cycles: number
  history: TopPidHistoryPoint[]
  matched_versions: Record<string, string[]>
}

export interface TopAnalysisResponse {
  cycle_count: number
  matched_versions: Record<string, string[]>
  time_range: { start: string; end: string }
  overview: TopOverview
  system_trends: TopSystemTrends
  cpu_top: TopCpuTopEntry[]
  mem_top: TopMemTopEntry[]
  process_categories: TopProcessCategories
  user_distribution: TopUserDistribution
  state_trends: TopStateTrends
  program_cpu_timeline: TopProgramCpuTimeline
}

// ─── /api/top/info 响应类型（时间点驱动视图专用）────────

export interface TopInfoResponse {
  cycle_count: number
  matched_versions: Record<string, string[]>
  time_range: { start: string; end: string }
  timestamps: string[]
  load_1m: number[]
}

// ─── /api/top/top_programs 响应类型（整个时间段的程序占用 TOP 20）──

export interface TopProgramsResponse {
  cpu_top: TopCpuTopEntry[]
  mem_top: TopMemTopEntry[]
  cycle_count: number
  matched_versions: Record<string, string[]>
}

// ─── /api/top/landscape 响应类型（多指标 landscape 图）────

export interface TopLandscapeSeries {
  name: string
  data: [string, number][]
}

export interface TopLandscapeResponse {
  pid: number | null
  agg: string
  metrics: string[]
  timestamps: string[]
  series: TopLandscapeSeries[]
  cycles_seen: number
  matched_versions: Record<string, string[]>
}

export const topApi = {
  /** 扫描目录，返回 top 格式文件列表（.dat / .dat.gz） */
  scan: (path: string, tool: string = 'top') => post<ScanResponse>('/scan', { path, tool }),

  /**
   * top 时间点驱动视图的轻量入口：返回时间戳列表 + load 1m（landscape）
   * - 响应 ~5KB（vs analyze 的 ~500KB）
   * - 首次 ~1s（parse），cache 命中 ~150ms
   */
  info: (dirPath: string, file: string) =>
    post<TopInfoResponse>('/top/info', {
      dir_path: dirPath,
      files: [file],
      parser_type: 'top',
      max_cycles: 50,
    }),

  /**
   * 取指定 cycle 的进程列表（默认按 %CPU 降序）
   * - 用于时间滑块切换时的实时加载
   * - 响应 ~7KB（50 个进程），cache 命中 ~150ms
   */
  snapshot: (dirPath: string, file: string, cycleIndex: number, sortBy: string = 'cpu_pct', sortDesc: boolean = true) =>
    post<TopSnapshotResponse>('/top/snapshot', {
      dir_path: dirPath,
      files: [file],
      parser_type: 'top',
      cycle_index: cycleIndex,
      sort_by: sortBy,
      sort_desc: sortDesc,
    }),

  /**
   * 第 1 段 landscape 图：多指标 chip + 聚合方式 + 可选 PID 搜索
   * - pid=null 时聚合全部进程，pid=N 时只取该 PID
   * - 响应 ~60KB（2 个指标，707 cycles），cache 命中 ~200ms
   */
  landscape: (
    dirPath: string,
    file: string,
    opts: { pid?: number | null; metrics: string[]; agg: 'avg' | 'max' | 'sum' },
  ) =>
    post<TopLandscapeResponse>('/top/landscape', {
      dir_path: dirPath,
      files: [file],
      parser_type: 'top',
      pid: opts.pid ?? null,
      metrics: opts.metrics,
      agg: opts.agg,
    }),

  /**
   * 取指定 PID 在所有 cycle 的时序（cpu/mem/state/res/virt 等）
   * - 用于点行查看该进程的全周期变化
   * - 响应 ~140KB（657 个历史点），cache 命中 ~150ms
   */
  pidHistory: (dirPath: string, file: string, pid: number) =>
    post<TopPidHistoryResponse>('/top/pid_history', {
      dir_path: dirPath,
      files: [file],
      parser_type: 'top',
      pid,
    }),

  /**
   * 第 2 段用：整个时间段的程序占用 TOP 20（按 command+user 跨所有 cycle 聚合）
   * - cpu_top：按 cpu_pct_max 降序前 20
   * - mem_top：按 res_kb_max 降序前 20
   * - 响应 ~12KB
   */
  topPrograms: (dirPath: string, file: string) =>
    post<TopProgramsResponse>('/top/top_programs', {
      dir_path: dirPath,
      files: [file],
      parser_type: 'top',
    }),

  /** 列出已注册的 top 格式版本 */
  listTopVersions: () => get<{ versions: TopVersionInfo[] }>('/top/versions'),
}
