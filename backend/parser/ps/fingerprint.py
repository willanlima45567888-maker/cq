"""
ps 文件 fingerprint 提取器。

从 ps .dat / .dat.gz 文件中提取：
  - banner：第 1 行（如 "Linux WQWbb v7.3.3"）
  - cycle_pattern：cycle 起始行正则（OSW 风格统一为 "zzz ***..."）
  - ps_header：进程表列名（13 列：USER/PID/PPID/.../COMMAND）

detect 阶段跟 versions/<id>/fingerprint.json 严格匹配。
"""

import gzip
import re
from pathlib import Path


# OSW 工具的 cycle 起始行模式（ps/iostat/top/mpstat 等通用）
CYCLE_PATTERN = re.compile(r'zzz\s+\*\*\*(.+)')


def extract_fingerprint(filepath: str | Path) -> dict:
    """从 ps 文件提取格式 fingerprint。

    Returns:
        {
            'banner': 'Linux WQWbb v7.3.3',            # 第 1 行
            'cycle_pattern': 'zzz\\s+\\*\\*\\*(.+)',     # cycle 起始正则
            'ps_header': ['USER', 'PID', 'PPID', ...],  # 进程表列名（顺序保留）
        }
    """
    p = Path(filepath)
    if str(p).endswith('.gz'):
        with gzip.open(p, mode='rt', encoding='utf-8', errors='replace') as f:
            text = f.read(8192)  # 8KB 够 1-2 个完整 cycle
    else:
        with open(p, encoding='utf-8', errors='replace') as f:
            text = f.read(8192)

    return {
        'banner': _extract_banner(text),
        'cycle_pattern': CYCLE_PATTERN.pattern,
        'ps_header': _extract_ps_header(text),
    }


def _extract_banner(text: str) -> str | None:
    """提取第 1 行 banner（去尾部换行）"""
    first_line = text.splitlines()[0] if text else None
    return first_line.strip() if first_line else None


def _extract_ps_header(text: str) -> list[str] | None:
    """找 PS 表 header 行（首字段是 USER，且包含 PID 和 COMMAND），split 取出列名。"""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        if parts[0] == 'USER' and 'PID' in parts and 'COMMAND' in parts:
            return parts
    return None
