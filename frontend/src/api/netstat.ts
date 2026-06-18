/**
 * OSW-View · netstat 工具专用 API
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

export interface NetstatVersionInfo {
  version: string
  display_name: string
  captured_at: string
  added_by: string
  notes: string
  banner?: string
  section_marker?: string
  active?: boolean
}

export interface UnknownFormatDetail {
  error: 'unknown_format'
  banner: string | null
  section_marker: string | null
  pending_path: string
}

// ─── /api/netstat/info 响应类型 ──────────────────────────

export interface NetstatInfoResponse {
  cycle_count: number
  matched_versions: Record<string, string[]>
  time_range: { start: string; end: string }
  timestamps: string[]
  interface_names: string[]
}

// ─── /api/netstat/snapshot 响应类型 ──────────────────────

export interface NetstatInterfaceState {
  name: string
  ifindex: number
  flags: string
  mtu: number
  state: string
  master: string
  link_addr: string
  altname: string
  rx_bytes: number
  rx_packets: number
  rx_errors: number
  rx_dropped: number
  rx_missed: number
  rx_mcast: number
  tx_bytes: number
  tx_packets: number
  tx_errors: number
  tx_dropped: number
  tx_carrier: number
  tx_collsns: number
}

export interface NetstatSnapshotResponse {
  cycle_index: number
  total_cycles: number
  timestamp: string
  interfaces: NetstatInterfaceState[]
  kernel_counters: Record<string, number>
  matched_versions: Record<string, string[]>
}

// ─── /api/netstat/landscape 响应类型 ────────────────────

export interface NetstatLandscapeSeries {
  name: string
  data: [string, number][]
}

export interface NetstatLandscapeResponse {
  interfaces: string[]
  metrics: string[]
  timestamps: string[]
  series: NetstatLandscapeSeries[]
  matched_versions: Record<string, string[]>
}

// ─── /api/netstat/kernel_landscape 响应类型 ────────────

export interface NetstatKernelLandscapeResponse {
  metrics: string[]
  timestamps: string[]
  series: NetstatLandscapeSeries[]
  matched_versions: Record<string, string[]>
}

// ─── /api/netstat/rates 响应类型（差分算速率）──────────

export interface NetstatInterfaceRates {
  rx_bytes_per_sec: number[]
  tx_bytes_per_sec: number[]
  rx_packets_per_sec: number[]
  tx_packets_per_sec: number[]
  rx_errors_per_sec: number[]
  tx_errors_per_sec: number[]
  rx_dropped_per_sec: number[]
  tx_dropped_per_sec: number[]
  rx_carrier_per_sec: number[]
  tx_collsns_per_sec: number[]
}

export interface NetstatRatesResponse {
  cycle_count: number
  timestamps: string[]
  interface_rates: Record<string, NetstatInterfaceRates>
  time_range: { start: string; end: string }
  // 累计字节（首末 cycle 差值）
  total_rx_bytes: number
  total_tx_bytes: number
  // 最后 cycle 的 kernel counter 快照
  last_kernel_counters: Record<string, number>
  matched_versions: Record<string, string[]>
}

// ─── /api/netstat/top_interfaces 响应类型 ──────────────

export interface NetstatTopInterfaceEntry {
  name: string
  rx_bytes: number
  tx_bytes: number
  state: string
  mtu: number
}

export interface NetstatTopInterfacesResponse {
  rx_bytes: NetstatTopInterfaceEntry[]
  tx_bytes: NetstatTopInterfaceEntry[]
  total_bytes: NetstatTopInterfaceEntry[]
  cycle_count: number
  matched_versions: Record<string, string[]>
}

// ─── /api/netstat/iface_trends 响应类型 ──────────────
// 总统概览 tab 用：每接口 12 个累计计数器的时序（不差分）

export interface NetstatIfaceTrendsSeries {
  name: string  // 形如 'ens1f0/rx_bytes'
  data: [string, number][]
}

export interface NetstatIfaceTrendsResponse {
  timestamps: string[]
  interface_names: string[]
  series: NetstatIfaceTrendsSeries[]
  matched_versions: Record<string, string[]>
}

export const netstatApi = {
  /** 扫描目录，返回 netstat 格式文件列表（.dat / .dat.gz） */
  scan: (path: string, tool: string = 'netstat') => post<{
    files: string[]
    scanned_dir: string
    cleaned_count: number
    tool: string
  }>('/scan', { path, tool }),

  /**
   * netstat 时间点驱动视图的轻量入口
   * - 返回时间戳列表 + 最后一个 cycle 的接口列表
   * - 首次 ~1s（parse），cache 命中 ~150ms
   */
  info: (dirPath: string, file: string) =>
    post<NetstatInfoResponse>('/netstat/info', {
      dir_path: dirPath,
      files: [file],
      parser_type: 'netstat',
      max_cycles: 50,
    }),

  /**
   * 取指定 cycle 的接口列表 + kernel_counters
   */
  snapshot: (dirPath: string, file: string, cycleIndex: number) =>
    post<NetstatSnapshotResponse>('/netstat/snapshot', {
      dir_path: dirPath,
      files: [file],
      parser_type: 'netstat',
      cycle_index: cycleIndex,
    }),

  /**
   * 多指标多接口时序图（landscape）
   * - 每个接口的每个指标一张时序图
   */
  landscape: (
    dirPath: string,
    file: string,
    interfaces: string[],
    metrics: string[],
  ) =>
    post<NetstatLandscapeResponse>('/netstat/landscape', {
      dir_path: dirPath,
      files: [file],
      parser_type: 'netstat',
      interfaces,
      metrics,
    }),

  /**
   * kernel counter 时序图（如 TcpRetransSegs / TcpAttemptFails / UdpInErrors 等）
   * - 每个 metric 一张时序图
   */
  kernelLandscape: (
    dirPath: string,
    file: string,
    metrics: string[],
  ) =>
    post<NetstatKernelLandscapeResponse>('/netstat/kernel_landscape', {
      dir_path: dirPath,
      files: [file],
      parser_type: 'netstat',
      metrics,
    }),

  /**
   * 计算每个接口的 RX/TX 速率（bytes/s, pps, errors/s）。
   * 算法：相邻 cycle 差分 / dt_sec（counter 单调递增）。
   * cycle[0] 设为 0（无前值）。
   */
  rates: (dirPath: string, file: string) =>
    post<NetstatRatesResponse>('/netstat/rates', {
      dir_path: dirPath,
      files: [file],
      parser_type: 'netstat',
    }),

  /**
   * 整个时间段的 TOP N 接口（按累计流量排序）
   */
  topInterfaces: (dirPath: string, file: string) =>
    post<NetstatTopInterfacesResponse>('/netstat/top_interfaces', {
      dir_path: dirPath,
      files: [file],
      parser_type: 'netstat',
    }),

  /**
   * 总统概览 tab：返回每接口 12 个累计计数器的时序（不差分）
   */
  ifaceTrends: (dirPath: string, file: string) =>
    post<NetstatIfaceTrendsResponse>('/netstat/iface_trends', {
      dir_path: dirPath,
      files: [file],
      parser_type: 'netstat',
    }),

  /** 列出已注册的 netstat 格式版本 */
  listNetstatVersions: () => get<{ versions: NetstatVersionInfo[] }>('/netstat/versions'),
}
