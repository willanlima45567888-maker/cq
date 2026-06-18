/**
 * OSW-View · iostat 工具专用 API
 *
 * 包含：
 *   - scan：扫描指定目录下的 .dat / .dat.gz
 *   - parse：解析选中的文件
 *   - listIostatVersions：列出已注册的 iostat 格式版本
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
  tool: string  // 本次扫描的工具子目录（如果有）
}

export interface ParseResponse {
  cycles_count: number
  devices: string[]
  metrics: string[]
  cpu_metrics: string[]
  data: {
    cycles: ParsedCycle[]
  }
  /** 本次解析命中的 iostat 版本：version_id -> [basenames] */
  matched_versions: Record<string, string[]>
}

export interface ParsedCycle {
  timestamp: string
  cpu: Record<string, number>
  devices: ParsedDevice[]
}

export interface ParsedDevice {
  device: string
  [key: string]: unknown
}

/** 后端 /api/iostat/versions 返回的版本项 */
export interface IostatVersionInfo {
  version: string
  display_name: string
  captured_at: string
  added_by: string
  notes: string
  banner: string
  /** 是否在前端展示。false 的版本（如 fingerprint 占位）会被过滤 */
  active?: boolean
}

/** 后端 422 unknown_format 的 detail */
export interface UnknownFormatDetail {
  error: 'unknown_format'
  banner: string | null
  header_columns: string[] | null
  pending_path: string
}

export const iostatApi = {
  /**
   * 扫描目录，返回 .dat / .dat.gz 文件列表
   * @param path 非空 → 直接扫该路径；为空 → 配合 tool 扫上传子目录
   * @param tool 工具名（iostat），path 为空时必填，扫 oswupdownload_file/iostat/
   */
  scan: (path: string, tool: string = 'iostat') => post<ScanResponse>('/scan', { path, tool }),

  /** 解析选中的文件 */
  parse: (dirPath: string, files: string[]) =>
    post<ParseResponse>('/parse', {
      dir_path: dirPath,
      files,
      parser_type: 'iostat',
    }),

  /** 列出已注册的 iostat 格式版本 */
  listIostatVersions: () =>
    get<{ versions: IostatVersionInfo[] }>('/iostat/versions'),
}
