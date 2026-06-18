/**
 * OSW-View 通用 API 封装（跨工具共享）
 *
 * 包含：
 *   - post / get 基础 fetch 包装
 *   - ApiError 统一错误
 *   - uploadFiles 通用上传（所有工具都把 .dat/.dat.gz 上传到 oswupdownload_file/）
 *   - clearCache 通用清缓存
 */

const BASE = '/api'

/** 携带 HTTP status 和后端 detail 对象的 Error */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: unknown,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

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

export interface UploadResponse {
  uploaded_count: number
  failed_count: number
  uploaded: Array<{ original: string; saved_as: string; path: string }>
  failed: Array<{ filename: string; reason: string }>
}

export const commonApi = {
  /** 上传一个或多个文件到 oswupdownload_file/<tool>/ 子目录
   * @param tool 工具名（iostat / ps / top ...），决定存到哪个子目录
   */
  uploadFiles: (files: FileList | File[], tool: string) => {
    const form = new FormData()
    form.append('tool', tool)
    for (const f of Array.from(files)) {
      form.append('files', f, f.name)
    }
    return fetch(BASE + '/upload', { method: 'POST', body: form }).then(async (res) => {
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
      return (await res.json()) as UploadResponse
    })
  },

  /** 清除解析缓存（指定 path 时只清一个文件，否则清全部） */
  clearCache: (path?: string) => post('/cache/clear', path ? { path } : {}),
}
