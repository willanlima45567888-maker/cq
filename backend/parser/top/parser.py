"""
top 工具解析器。

TOP 工具的数据结构（与 ps 的区别）：
  - 每个 cycle 包含：
    1) summary 块（top header + Tasks + %Cpu + Mem + Swap）：系统级指标
    2) processes 列表：12 列进程表（PID/USER/PR/NI/VIRT/RES/SHR/S/%CPU/%MEM/TIME+/COMMAND）
  - 进程 COMMAND 字段可能含空格，按列切分时 COMMAND 取剩余整行
  - VIRT / RES / SHR 字段可能带单位后缀：纯数字 = KB，"161.5g" = GB
  - TIME+ 字段格式：HH:MM:SS.cc（如 "0:01.22"、"2195:37.00"）
  - 每个 cycle 之间用 "zzz ***<timestamp>" 分隔（与 ps 完全一致）

不复用 backend/parser/base.py（base.py 是 iostat 专用的 cpu/device 状态机）。
"""

import gzip
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# ─── 摘要块字段定义 ────────────────────────────────────────────

@dataclass
class TopSummary:
    """一个 cycle 的系统摘要（top header + Tasks + %Cpu + Mem + Swap）"""
    # 来自 "top - HH:MM:SS up X days, HH:MM, N users, load average: A, B, C"
    time_str: str = ''           # HH:MM:SS
    up_days: int = 0             # up X days
    up_hours: int = 0            # 11:04 → 11
    up_minutes: int = 0          # 11:04 → 4
    users: int = 0
    load_avg_1m: float = 0.0
    load_avg_5m: float = 0.0
    load_avg_15m: float = 0.0

    # 来自 "Tasks: N1 total, N2 running, N3 sleeping, N4 stopped, N5 zombie"
    tasks_total: int = 0
    tasks_running: int = 0
    tasks_sleeping: int = 0
    tasks_stopped: int = 0
    tasks_zombie: int = 0

    # 来自 "%Cpu(s): X us, Y sy, Z ni, ... st"
    cpu_us: float = 0.0
    cpu_sy: float = 0.0
    cpu_ni: float = 0.0
    cpu_id: float = 0.0
    cpu_wa: float = 0.0
    cpu_hi: float = 0.0
    cpu_si: float = 0.0
    cpu_st: float = 0.0

    # 来自 "MiB Mem : total, free, used, buff/cache"
    mem_total_mib: float = 0.0
    mem_free_mib: float = 0.0
    mem_used_mib: float = 0.0
    mem_buff_cache_mib: float = 0.0

    # 来自 "MiB Swap: total, free, used. avail Mem"
    swap_total_mib: float = 0.0
    swap_free_mib: float = 0.0
    swap_used_mib: float = 0.0
    avail_mem_mib: float = 0.0


# ─── 进程 dataclass ───────────────────────────────────────────

@dataclass
class TopProcess:
    """一个进程（12 列：PID/USER/PR/NI/VIRT/RES/SHR/S/%CPU/%MEM/TIME+/COMMAND）"""
    pid: int = 0
    user: str = ''
    pr: int = 0
    ni: int = 0
    virt_kb: int = 0          # 归一化到 KB（"161.5g" → 161.5 * 1024 * 1024 = 169114337）
    res_kb: int = 0           # 归一化到 KB
    shr_kb: int = 0           # 归一化到 KB
    s: str = ''               # 状态
    cpu_pct: float = 0.0
    mem_pct: float = 0.0
    time_str: str = ''        # 原始 TIME+ 文本（如 "0:01.22"）
    command: str = ''


# ─── Cycle + Result ───────────────────────────────────────────

@dataclass
class TopCycle:
    """一个采集周期（含 summary + processes）"""
    timestamp: str
    summary: TopSummary = field(default_factory=TopSummary)
    processes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TopParseResult:
    cycles: list[TopCycle]


# ─── OSW cycle 起始行（ps/iostat/top/mpstat 等通用）──────────────
CYCLE_PATTERN = re.compile(r'zzz\s+\*\*\*(.+)')


# ─── 辅助：行解析器 ────────────────────────────────────────────

_TOP_HEADER_RE = re.compile(
    r'^top\s+-\s+(\d{2}:\d{2}:\d{2})\s+up\s+(?:(\d+)\s+days?,\s+)?(\d{1,2}):(\d{2})(?:,\s+(\d+)\s+users?,\s+load\s+average:\s+([\d.]+),\s+([\d.]+),\s+([\d.]+))?'
)
_TASKS_RE = re.compile(
    r'Tasks:\s*(\d+)\s+total,\s*(\d+)\s+running,\s*(\d+)\s+sleeping,\s*(\d+)\s+stopped,\s*(\d+)\s+zombie'
)
_CPU_RE = re.compile(
    r'%?Cpu\(s\):\s*([\d.]+)\s+us,\s*([\d.]+)\s+sy,\s*([\d.]+)\s+ni,\s*([\d.]+)\s+id,\s*([\d.]+)\s+wa,\s*([\d.]+)\s+hi,\s*([\d.]+)\s+si,\s*([\d.]+)\s+st'
)
_MEM_RE = re.compile(
    r'MiB\s+Mem\s*:\s*([\d.]+)\s+total,\s*([\d.]+)\s+free,\s*([\d.]+)\s+used,\s*([\d.]+)\s+buff/cache'
)
_SWAP_RE = re.compile(
    r'MiB\s+Swap:\s*([\d.]+)\s+total,\s*([\d.]+)\s+free,\s*([\d.]+)\s+used\.\s+([\d.]+)\s+avail\s+Mem'
)


def _parse_size_to_kb(token: str) -> int:
    """把 VIRT/RES/SHR 值归一化到 KB。

    支持的单位后缀：g/G（GB）、m/M（MB）、t/T（TB），无后缀 = KB。
    例：
      '5268'       → 5268
      '161.5g'     → int(161.5 * 1024 * 1024) = 169114337
      '2446504'    → 2446504
    """
    if not token:
        return 0
    token = token.strip()
    m = re.match(r'^([\d.]+)\s*([gGmMtT]?)$', token)
    if not m:
        try:
            return int(float(token))
        except (ValueError, TypeError):
            return 0
    num = float(m.group(1))
    unit = m.group(2).lower()
    if unit == 'g':
        return int(num * 1024 * 1024)
    if unit == 'm':
        return int(num * 1024)
    if unit == 't':
        return int(num * 1024 * 1024 * 1024)
    # 无单位 = KB
    return int(num)


def _parse_top_header_line(line: str, summary: TopSummary) -> None:
    """解析 'top - 01:00:09 up 10 days, 11:04, 1 user, load average: 1.68, 1.46, 1.55'"""
    m = _TOP_HEADER_RE.match(line)
    if not m:
        return
    summary.time_str = m.group(1) or ''
    summary.up_days = int(m.group(2) or 0)
    summary.up_hours = int(m.group(3) or 0)
    summary.up_minutes = int(m.group(4) or 0)
    summary.users = int(m.group(5) or 0)
    summary.load_avg_1m = float(m.group(6) or 0.0)
    summary.load_avg_5m = float(m.group(7) or 0.0)
    summary.load_avg_15m = float(m.group(8) or 0.0)


def _parse_tasks_line(line: str, summary: TopSummary) -> None:
    """解析 'Tasks: 2145 total, 2 running, 2141 sleeping, 1 stopped, 1 zombie'"""
    m = _TASKS_RE.search(line)
    if not m:
        return
    summary.tasks_total = int(m.group(1))
    summary.tasks_running = int(m.group(2))
    summary.tasks_sleeping = int(m.group(3))
    summary.tasks_stopped = int(m.group(4))
    summary.tasks_zombie = int(m.group(5))


def _parse_cpu_line(line: str, summary: TopSummary) -> None:
    """解析 '%Cpu(s): 1.2 us, 0.4 sy, 0.0 ni, 98.2 id, 0.0 wa, 0.0 hi, 0.1 si, 0.0 st'"""
    m = _CPU_RE.search(line)
    if not m:
        return
    summary.cpu_us = float(m.group(1))
    summary.cpu_sy = float(m.group(2))
    summary.cpu_ni = float(m.group(3))
    summary.cpu_id = float(m.group(4))
    summary.cpu_wa = float(m.group(5))
    summary.cpu_hi = float(m.group(6))
    summary.cpu_si = float(m.group(7))
    summary.cpu_st = float(m.group(8))


def _parse_mem_line(line: str, summary: TopSummary) -> None:
    """解析 'MiB Mem : 256245.4 total, 44510.4 free, 146779.1 used, 64955.9 buff/cache'"""
    m = _MEM_RE.search(line)
    if not m:
        return
    summary.mem_total_mib = float(m.group(1))
    summary.mem_free_mib = float(m.group(2))
    summary.mem_used_mib = float(m.group(3))
    summary.mem_buff_cache_mib = float(m.group(4))


def _parse_swap_line(line: str, summary: TopSummary) -> None:
    """解析 'MiB Swap: 16384.0 total, 16384.0 free, 0.0 used. 63580.6 avail Mem'"""
    m = _SWAP_RE.search(line)
    if not m:
        return
    summary.swap_total_mib = float(m.group(1))
    summary.swap_free_mib = float(m.group(2))
    summary.swap_used_mib = float(m.group(3))
    summary.avail_mem_mib = float(m.group(4))


def _parse_process_line(line: str, top_header: list[str], column_mapping: dict[str, str]) -> dict[str, Any] | None:
    """解析一行 top 进程数据。

    列结构（12 列，top_header 顺序）：
      0: PID          1 token
      1: USER         1 token
      2: PR           1 token
      3: NI           1 token
      4: VIRT         1 token（可能带 g/m/t 单位）
      5: RES          1 token
      6: SHR          1 token
      7: S            1 token（状态）
      8: %CPU         1 token
      9: %MEM         1 token
      10: TIME+       1 token（HH:MM:SS.cc）
      11: COMMAND     剩余整行
    """
    tokens = line.split()
    if len(tokens) < 12:
        return None

    proc: dict[str, Any] = {}
    idx = 0

    for i, raw_col in enumerate(top_header):
        std_name = column_mapping.get(raw_col, raw_col.lower())

        if i < 10:
            # 前 10 列固定 1 token
            if idx >= len(tokens):
                return None
            if i == 0:  # PID
                try:
                    proc[std_name] = int(tokens[idx])
                except (ValueError, TypeError):
                    proc[std_name] = 0
            elif i == 2:  # PR
                try:
                    proc[std_name] = int(tokens[idx])
                except (ValueError, TypeError):
                    proc[std_name] = 0
            elif i == 3:  # NI
                try:
                    proc[std_name] = int(tokens[idx])
                except (ValueError, TypeError):
                    proc[std_name] = 0
            elif i == 4:  # VIRT（带单位，归一化 KB）
                proc[std_name] = _parse_size_to_kb(tokens[idx])
            elif i == 5:  # RES
                proc[std_name] = _parse_size_to_kb(tokens[idx])
            elif i == 6:  # SHR
                proc[std_name] = _parse_size_to_kb(tokens[idx])
            elif i == 8:  # %CPU
                try:
                    proc[std_name] = float(tokens[idx])
                except (ValueError, TypeError):
                    proc[std_name] = 0.0
            elif i == 9:  # %MEM
                try:
                    proc[std_name] = float(tokens[idx])
                except (ValueError, TypeError):
                    proc[std_name] = 0.0
            else:
                # USER (i=1) / S (i=7) — 字符串
                proc[std_name] = tokens[idx]
            idx += 1
        elif i == 10:
            # TIME+：1 token
            if idx >= len(tokens):
                return None
            proc[std_name] = tokens[idx]
            idx += 1
        elif i == 11:
            # COMMAND：剩余整行
            proc[std_name] = ' '.join(tokens[idx:]) if idx < len(tokens) else ''
            break  # COMMAND 是最后一列

    return proc


# ─── 主解析函数 ──────────────────────────────────────────────

def parse_top_file(
    filepath: str,
    top_header: list[str],
    column_mapping: dict[str, str] | None = None,
) -> TopParseResult:
    """解析 top 文件。

    Args:
        filepath: .dat 或 .dat.gz 路径
        top_header: 进程表列名（12 列：PID/USER/.../COMMAND）
        column_mapping: 原始列名 → 标准化字段名（可选）

    Returns:
        TopParseResult(cycles=[TopCycle(timestamp, summary, processes=[...]), ...])
    """
    if column_mapping is None:
        column_mapping = {h: h.lower() for h in top_header}

    cycles: list[TopCycle] = []
    current_cycle: TopCycle | None = None
    current_state: str = 'idle'  # 'idle' / 'in_summary' / 'in_processes'

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
                    cycles.append(current_cycle)
                ts_str = m.group(1).strip()
                dt = _parse_timestamp(ts_str)
                current_cycle = TopCycle(
                    timestamp=dt.isoformat() if dt else ts_str,
                    summary=TopSummary(),
                )
                current_state = 'in_summary'
                continue

            # 2) 还没遇到 cycle 起始 → 跳过（banner、header、空行）
            if current_cycle is None:
                continue

            # 3) 摘要块解析（直到遇到 column header 行）
            if current_state == 'in_summary':
                if line.startswith('top -'):
                    _parse_top_header_line(line, current_cycle.summary)
                    continue
                if 'Tasks:' in line:
                    _parse_tasks_line(line, current_cycle.summary)
                    continue
                if '%Cpu' in line or 'Cpu(s):' in line:
                    _parse_cpu_line(line, current_cycle.summary)
                    continue
                if 'MiB Mem' in line:
                    _parse_mem_line(line, current_cycle.summary)
                    continue
                if 'MiB Swap' in line:
                    _parse_swap_line(line, current_cycle.summary)
                    continue
                # 列头行（首列 PID + 含 COMMAND + %CPU + 12 列）→ 切到 processes
                parts = line.split()
                if (
                    len(parts) == 12
                    and parts[0] == 'PID'
                    and 'COMMAND' in parts
                    and '%CPU' in parts
                ):
                    current_state = 'in_processes'
                    continue
                # 其它行（如空行、其它注释）→ 跳过
                continue

            # 4) 进程数据行
            if current_state == 'in_processes':
                # 下一个 cycle 的 zzz 行已被步骤 1 捕获
                # 空行说明该 cycle 结束，回到 idle
                if not line.strip():
                    current_state = 'idle'
                    continue
                proc = _parse_process_line(line, top_header, column_mapping)
                if proc is not None:
                    current_cycle.processes.append(proc)
    finally:
        f.close()

    if current_cycle is not None:
        cycles.append(current_cycle)

    return TopParseResult(cycles=cycles)


def _parse_timestamp(ts_str: str) -> datetime | None:
    """解析 'Sun Jun 7 01:00:03 CST 2026' 这种格式"""
    try:
        ts_clean = re.sub(r'\s+(CST|CDT)\s+', ' ', ts_str)
        return datetime.strptime(ts_clean, '%a %b %d %H:%M:%S %Y')
    except ValueError:
        return None
