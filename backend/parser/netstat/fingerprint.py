"""
netstat 文件 fingerprint 提取器。

从 netstat .dat / .dat.gz 文件中提取：
  - banner：第 1 行（如 "Linux OSWbb v22.1.0AHF rs-26cmmdb-dg1"）
  - cycle_pattern：cycle 起始行正则（OSW 风格统一为 "zzz ***..."）
  - section_marker：识别 #kernel 节的标志字符串（用于确认文件结构）

detect 阶段跟 versions/<id>/fingerprint.json 匹配。
"""

import gzip
import re
from pathlib import Path


# OSW 工具的 cycle 起始行模式（ps/iostat/top/netstat 等通用）
CYCLE_PATTERN = re.compile(r'zzz\s+\*\*\*(.+)')

# 段标记：识别 netstat 特有的 #kernel 段
KERNEL_SECTION_MARKER = '#kernel'

# 接口行：`数字: name: <flags...> mtu N qdisc ... state X mode ...`
#  - 例：`3: ens65f0: <BROADCAST,MULTICAST,SLAVE,UP,LOWER_UP> mtu 1500 ...`
_INTERFACE_LINE_RE = re.compile(r'^\d+:\s+([^:]+):\s+<([^>]+)>')

# RX/TX header 行
_RX_HEADER_RE = re.compile(r'^\s+RX:\s+(.+)')
_TX_HEADER_RE = re.compile(r'^\s+TX:\s+(.+)')

# 数字行（5-6 列）：bytes packets errors dropped missed mcast [carrier collsns]
_NUMERIC_5COL_RE = re.compile(r'^\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$')
_NUMERIC_6COL_RE = re.compile(r'^\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$')


def extract_fingerprint(filepath: str | Path) -> dict:
    """从 netstat 文件提取格式 fingerprint。

    Returns:
        {
            'banner': 'Linux OSWbb v22.1.0AHF rs-26cmmdb-dg1',  # 第 1 行
            'cycle_pattern': r'zzz\\s+\\*\\*\\*(.+)',             # cycle 起始正则
            'section_marker': '#kernel',                       # 段标记
        }
    """
    p = Path(filepath)
    if str(p).endswith('.gz'):
        with gzip.open(p, mode='rt', encoding='utf-8', errors='replace') as f:
            text = f.read(16384)  # 多读一些确保能扫到第一个 #kernel
    else:
        with open(p, encoding='utf-8', errors='replace') as f:
            text = f.read(16384)

    return {
        'banner': _extract_banner(text),
        'cycle_pattern': CYCLE_PATTERN.pattern,
        'section_marker': _extract_section_marker(text),
    }


def _extract_banner(text: str) -> str | None:
    """提取 netstat 文件的 banner。

    跳过文件头部的 AHF 提示行，找包含 "Linux" 的行作为 banner。
    例：
      It is recommended to use System Health Monitor...
      Linux OSWbb v22.1.0AHF rs-26cmmdb-dg1   ← banner
      zzz ***Mon Jun 15 13:00:04 CST 2026
    """
    for line in text.splitlines()[:10]:  # 前 10 行够用
        line = line.strip()
        if line.startswith('Linux '):
            return line
    # 兜底：第 1 行
    first = text.splitlines()[0] if text else ''
    return first.strip() if first else None


def _extract_section_marker(text: str) -> str | None:
    """找第一个 #kernel 段标记（确认 netstat 文件结构）。"""
    for line in text.splitlines():
        if line.strip() == KERNEL_SECTION_MARKER:
            return KERNEL_SECTION_MARKER
    return None
