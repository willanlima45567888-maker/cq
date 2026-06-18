"""
iostat 文件 fingerprint 提取器。

从 .dat.gz 中提取格式元数据（banner、device header、cpu header），
用于 detect 阶段跟 versions/<id>/fingerprint.json 比对。
"""

import gzip
import re
from pathlib import Path


def extract_fingerprint(filepath: str | Path) -> dict:
    """从 iostat 文件提取格式 fingerprint。

    Returns:
        {
            'banner': 'Linux OSWbb v7.3.3',     # 第 1 行
            'device_header': ['rrqm/s', ...],   # Device 行列名（顺序保留）
            'cpu_header': ['%user', ...],       # avg-cpu 行列名（顺序保留）
        }
    """
    p = Path(filepath)
    if str(p).endswith('.gz'):
        with gzip.open(p, mode='rt', encoding='utf-8', errors='replace') as f:
            text = f.read(8192)  # 8KB 够覆盖 1-2 个完整 cycle
    else:
        with open(p, encoding='utf-8', errors='replace') as f:
            text = f.read(8192)

    return {
        'banner': _extract_banner(text),
        'device_header': _extract_section_columns(text, 'Device'),
        'cpu_header': _extract_section_columns(text, 'avg-cpu'),
    }


def _extract_banner(text: str) -> str | None:
    """提取第 1 行 banner（去尾部换行）"""
    first_line = text.splitlines()[0] if text else None
    return first_line.strip() if first_line else None


def _extract_section_columns(text: str, section_name: str) -> list[str] | None:
    """找第一个以 `<section_name>[:]?` 开头的行，split 取出列名（保留顺序）"""
    pattern = re.compile(rf'^{re.escape(section_name)}\b\s*[:]?\s*(.*)$', re.MULTILINE)
    for line in text.splitlines():
        m = pattern.match(line)
        if m and m.group(1).strip():
            return m.group(1).split()
    return None
