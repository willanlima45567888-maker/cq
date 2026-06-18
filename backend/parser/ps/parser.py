"""
ps 工具解析器。

PS 工具的数据结构（区别于 iostat）：
  - 每个 cycle 是一张进程表（timestamp + 进程列表）
  - 没有 avg-cpu / device 概念
  - 进程 COMMAND 字段可能含空格，按列切分时 COMMAND 取剩余整行
  - STARTED 字段可能是 1 token（HH:MM:SS）或 2 token（MMM DD），
    启发式判断：字母开头 = 2 token，数字开头 = 1 token

不复用 backend/parser/base.py（base.py 是 iostat 专用的 cpu/device 状态机）。
"""

import gzip
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class PsProcess:
    """一个进程"""
    user: str = ''
    pid: int = 0
    ppid: int = 0
    pri: int = 0
    cpu_pct: float = 0.0
    mem_pct: float = 0.0
    vsz: int = 0
    rss: int = 0
    wchan: str = ''
    s: str = ''
    started: str = ''
    time: str = ''
    command: str = ''


@dataclass
class PsCycle:
    """一个采集周期"""
    timestamp: str
    processes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PsParseResult:
    cycles: list[PsCycle]


# OSW cycle 起始行（ps/iostat/top/mpstat 等通用）
CYCLE_PATTERN = re.compile(r'zzz\s+\*\*\*(.+)')

# 数字列的标准化字段名（用于类型转换）
INT_FIELDS = {'pid', 'ppid', 'pri', 'vsz', 'rss'}
FLOAT_FIELDS = {'cpu_pct', 'mem_pct'}


def _parse_timestamp(ts_str: str) -> datetime | None:
    """解析 'Sun Jun 7 01:00:03 CST 2026' 这种格式"""
    try:
        ts_clean = re.sub(r'\s+(CST|CDT)\s+', ' ', ts_str)
        return datetime.strptime(ts_clean, '%a %b %d %H:%M:%S %Y')
    except ValueError:
        return None


def _convert_value(value: str, std_name: str) -> Any:
    """根据标准化字段名做类型转换"""
    if std_name in INT_FIELDS:
        try:
            return int(value)
        except (ValueError, TypeError):
            return 0
    if std_name in FLOAT_FIELDS:
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0
    return value


def _parse_process_line(line: str, ps_header: list[str], column_mapping: dict[str, str]) -> dict[str, Any] | None:
    """解析一行 ps 进程数据。

    列结构（ps_header 顺序）：
      0: USER         1 token
      1: PID          1 token
      2: PPID         1 token
      3: PRI          1 token
      4: %CPU         1 token
      5: %MEM         1 token
      6: VSZ          1 token
      7: RSS          1 token
      8: WCHAN        1 token
      9: S            1 token
      10: STARTED     1 token (HH:MM:SS) 或 2 token (MMM DD)
      11: TIME        1 token (HH:MM:SS)
      12: COMMAND     剩余所有 token（可能含空格）

    启发式：STARTED 字段字母开头（Jan/Feb/.../Dec）= 2 token，否则 = 1 token
    """
    tokens = line.split()
    if len(tokens) < 12:
        return None

    proc: dict[str, Any] = {}
    idx = 0

    for i, raw_col in enumerate(ps_header):
        std_name = column_mapping.get(raw_col, raw_col.lower())

        if i < 10:
            # 前 10 列固定 1 token
            if idx >= len(tokens):
                return None
            proc[std_name] = _convert_value(tokens[idx], std_name)
            idx += 1
        elif i == 10:
            # STARTED 字段：1 或 2 token
            if idx >= len(tokens):
                return None
            if re.match(r'^[A-Za-z]', tokens[idx]):
                # 字母开头（月份缩写）= 2 token
                if idx + 1 < len(tokens):
                    proc[std_name] = f'{tokens[idx]} {tokens[idx + 1]}'
                    idx += 2
                else:
                    proc[std_name] = tokens[idx]
                    idx += 1
            else:
                # 数字开头 = 1 token
                proc[std_name] = tokens[idx]
                idx += 1
        elif i == 11:
            # TIME：1 token
            if idx >= len(tokens):
                return None
            proc[std_name] = tokens[idx]
            idx += 1
        elif i == 12:
            # COMMAND：剩余整行
            proc[std_name] = ' '.join(tokens[idx:]) if idx < len(tokens) else ''
            break  # COMMAND 是最后一列

    return proc


def parse_ps_file(
    filepath: str,
    ps_header: list[str],
    column_mapping: dict[str, str] | None = None,
) -> PsParseResult:
    """解析 ps 文件。

    Args:
        filepath: .dat 或 .dat.gz 路径
        ps_header: 进程表列名（13 列：USER/PID/.../COMMAND）
        column_mapping: 原始列名 → 标准化字段名（可选）

    Returns:
        PsParseResult(cycles=[PsCycle(timestamp, processes=[...]), ...])
    """
    if column_mapping is None:
        column_mapping = {h: h.lower() for h in ps_header}

    cycles: list[PsCycle] = []
    current_cycle: dict | None = None

    if str(filepath).endswith('.gz'):
        f = gzip.open(filepath, mode='rt', encoding='utf-8', errors='replace')
    else:
        f = open(filepath, encoding='utf-8', errors='replace')

    try:
        for raw_line in f:
            line = raw_line.rstrip()

            # 1) cycle 起始行
            m = CYCLE_PATTERN.match(line)
            if m:
                if current_cycle is not None:
                    cycles.append(_finalize_cycle(current_cycle))
                ts_str = m.group(1).strip()
                dt = _parse_timestamp(ts_str)
                current_cycle = {
                    'timestamp': dt.isoformat() if dt else ts_str,
                    'processes': [],
                }
                continue

            # 2) 还没遇到 cycle 起始 → 跳过（banner、header、空行）
            if current_cycle is None:
                continue

            # 3) header 行（首列 USER）→ 跳过
            parts = line.split()
            if len(parts) >= 3 and parts[0] == 'USER' and 'PID' in parts:
                continue

            # 4) 数据行
            proc = _parse_process_line(line, ps_header, column_mapping)
            if proc is not None:
                current_cycle['processes'].append(proc)
    finally:
        f.close()

    if current_cycle is not None:
        cycles.append(_finalize_cycle(current_cycle))

    return PsParseResult(cycles=cycles)


def _finalize_cycle(cycle: dict) -> PsCycle:
    return PsCycle(
        timestamp=cycle['timestamp'],
        processes=cycle['processes'],
    )

