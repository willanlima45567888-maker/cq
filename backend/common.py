"""
OSW-View 后端通用代码（跨工具共享）。

目录结构约定：
  oswupdownload_file/
  ├── iostat/   ← iostat 工具的上传文件
  ├── ps/       ← ps 工具的上传文件（未来）
  └── top/      ← top 工具的上传文件（未来）

每个工具的上传文件存在自己的子目录里，互不污染。

包含：
  - 上传目录配置（UPLOAD_DIR / UPLOAD_RETENTION_DAYS）
  - 通用文件后缀白名单（SUPPORTED_SUFFIXES）
  - 工具子目录工具函数：get_upload_dir(tool) / scan_tool_dir(tool) / cleanup_tool_dir(tool)
  - 启动时遍历所有已知工具子目录做懒清理

工具专属代码（iostat / 未来 ps / top / netstat ...）请放在 backend/parser/<tool>/ 下，
不要放这里。
"""

import glob
import os
import time
from pathlib import Path

# ─── 配置 ────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR_NAME = 'oswupdownload_file'
UPLOAD_DIR = PROJECT_ROOT / UPLOAD_DIR_NAME
UPLOAD_RETENTION_DAYS = 7  # 文件 mtime 超过此天数则自动删除

# 允许扫描的文件后缀（iostat 在用；未来 ps/top 可能加 .log/.out 等）
SUPPORTED_SUFFIXES = ('.dat.gz', '.dat')

# 工具白名单：合法的子目录名
# 加新工具时这里要同步加
KNOWN_TOOLS: tuple[str, ...] = ('iostat', 'ps', 'top', 'mpstat', 'vmstat', 'netstat', 'meminfo', 'lsof')


# ─── 工具子目录函数 ──────────────────────────────────────────────────


def get_upload_dir(tool: str) -> Path:
    """获取指定工具的上传子目录路径：UPLOAD_DIR / <tool>。

    不检查路径是否存在，调用方按需 mkdir。
    """
    return UPLOAD_DIR / tool


def ensure_upload_dir(tool: str) -> Path:
    """mkdir -p 并返回工具子目录路径。"""
    d = get_upload_dir(tool)
    d.mkdir(parents=True, exist_ok=True)
    return d


def scan_tool_dir(tool: str) -> list[str]:
    """扫描工具子目录下的所有 SUPPORTED_SUFFIXES 文件，返回排序后的绝对路径列表。"""
    target = get_upload_dir(tool)
    if not target.is_dir():
        return []
    found: list[str] = []
    for suffix in SUPPORTED_SUFFIXES:
        pattern = os.path.join(str(target), '*' + suffix)
        found.extend(glob.glob(pattern))
    return sorted(set(found))


def cleanup_tool_dir(tool: str, retention_days: int = UPLOAD_RETENTION_DAYS) -> int:
    """清理指定工具子目录里 mtime 超过 retention_days 的文件，返回删除数量。

    只清理一级子文件（不递归），避免误删用户期望保留的子目录结构。
    """
    target = get_upload_dir(tool)
    if not target.exists() or not target.is_dir():
        return 0
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for entry in target.iterdir():
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError:
            # 文件可能在并发清理中被删；忽略
            pass
    return removed


def cleanup_all_tool_dirs(retention_days: int = UPLOAD_RETENTION_DAYS) -> dict[str, int]:
    """遍历所有 KNOWN_TOOLS 子目录做清理，返回 {tool: removed_count}。"""
    results: dict[str, int] = {}
    for tool in KNOWN_TOOLS:
        results[tool] = cleanup_tool_dir(tool, retention_days)
    return results


# ─── 旧的通用工具函数（保留兼容：按绝对路径扫描/清理）─────────────────


def cleanup_expired_files(dir_path: Path, retention_days: int) -> int:
    """删除 dir_path 下 mtime 超过 retention_days 的文件，返回删除数量。

    工具子目录的清理请用 cleanup_tool_dir()；本函数保留给用户自定义绝对路径场景。
    """
    if not dir_path.exists() or not dir_path.is_dir():
        return 0
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for entry in dir_path.iterdir():
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def scan_supported_files(dir_path: str) -> list[str]:
    """扫描 dir_path 下所有 SUPPORTED_SUFFIXES 文件，返回排序后的绝对路径列表。

    工具子目录的扫描请用 scan_tool_dir()；本函数保留给用户自定义绝对路径场景。
    """
    found: list[str] = []
    for suffix in SUPPORTED_SUFFIXES:
        pattern = os.path.join(dir_path, '*' + suffix)
        found.extend(glob.glob(pattern))
    return sorted(set(found))


# ─── 启动时懒清理（遍历所有 KNOWN_TOOLS 子目录）─────────────────────

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
_startup_results = cleanup_all_tool_dirs(UPLOAD_RETENTION_DAYS)
_total_cleaned = sum(_startup_results.values())
if _total_cleaned:
    detail = ', '.join(f'{tool}={n}' for tool, n in _startup_results.items() if n)
    print(f'[startup] 已清理超过 {UPLOAD_RETENTION_DAYS} 天的文件：{detail}')
