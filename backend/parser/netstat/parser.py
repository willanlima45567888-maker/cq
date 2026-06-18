"""
netstat 工具解析器。

NETSTAT 工具的数据结构（与 top 的区别）：
  - 每个 cycle 包含：
    1) interfaces 列表：`ip -s link` 输出（每个网络接口的状态 + RX/TX 计数器）
    2) kernel_counters dict：`/proc/net/snmp` 解析的 key-value（IP/ICMP/TCP/UDP/IP6/TcpExt/IpExt/MPTcpExt）
  - 接口行格式：`数字: name: <flags> mtu N qdisc ... state X mode ...`
  - 紧跟 link 行（mac 地址）、RX header、RX 数字行、TX header、TX 数字行
  - 接口块用空行分隔
  - kernel counters 段以 `#kernel` 开头，每行 `Key<spaces>Value<spaces>Rate`
  - 每个 cycle 之间用 "zzz ***<timestamp>" 分隔（与 ps/top 一致）

不复用 backend/parser/top/parser.py（top 解析 summary + processes，netstat 解析 interfaces + counters）。
"""

import gzip
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# ─── 接口 dataclass ───────────────────────────────────────────

@dataclass
class NetstatInterface:
    """一个网络接口（含状态 + RX/TX 计数器）"""
    name: str = ''
    ifindex: int = 0              # 数字: 字段
    flags: str = ''                # <BROADCAST,MULTICAST,UP,...>
    mtu: int = 0
    qdisc: str = ''
    state: str = ''                # UP / DOWN / UNKNOWN
    mode: str = ''                 # DEFAULT
    master: str = ''               # master bondX（可选）
    link_type: str = ''            # link/ether / link/loopback
    link_addr: str = ''            # mac 地址
    altname: str = ''              # altname enpXXsXfY

    # RX 统计
    rx_bytes: int = 0
    rx_packets: int = 0
    rx_errors: int = 0
    rx_dropped: int = 0
    rx_missed: int = 0
    rx_mcast: int = 0

    # TX 统计
    tx_bytes: int = 0
    tx_packets: int = 0
    tx_errors: int = 0
    tx_dropped: int = 0
    tx_carrier: int = 0
    tx_collsns: int = 0


# ─── Cycle + Result ───────────────────────────────────────────

@dataclass
class NetstatCycle:
    """一个采集周期（含 interfaces + kernel_counters）"""
    timestamp: str
    interfaces: list[dict[str, Any]] = field(default_factory=list)
    kernel_counters: dict[str, int] = field(default_factory=dict)


@dataclass
class NetstatParseResult:
    cycles: list[NetstatCycle]


# ─── 状态机常量 ───────────────────────────────────────────────

INTERFACE_LINE_RE = re.compile(r'^(\d+):\s+(\S+):\s+<([^>]+)>')
MTU_RE = re.compile(r'mtu\s+(\d+)')
QDISC_RE = re.compile(r'qdisc\s+(\S+)')
STATE_RE = re.compile(r'state\s+(\S+)')
MODE_RE = re.compile(r'mode\s+(\S+)')
MASTER_RE = re.compile(r'master\s+(\S+)')
LINK_RE = re.compile(r'link/(\S+)\s+(\S+)')
ALTNAME_RE = re.compile(r'altname\s+(\S+)')
RX_HEADER_RE = re.compile(r'^\s+RX:\s+(\S+(?:\s+\S+)*?)\s*$')
TX_HEADER_RE = re.compile(r'^\s+TX:\s+(\S+(?:\s+\S+)*?)\s*$')
NUMERIC_RE = re.compile(r'^\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)(?:\s+(\d+))?\s*$')

# kernel counter 行：`Key<spaces>Value<spaces>Rate`
# 例：`IpInReceives                    471370721          0.0`
KERNEL_COUNTER_RE = re.compile(r'^(\S+)\s+(\d+)\s+\S+\s*$')

KERNEL_SECTION_MARKER = '#kernel'


# ─── 主解析函数 ──────────────────────────────────────────────

def parse_netstat_file(
    filepath: str,
    section_marker: str = KERNEL_SECTION_MARKER,
) -> NetstatParseResult:
    """解析 netstat 文件。

    Args:
        filepath: .dat 或 .dat.gz 路径
        section_marker: 段标记（默认 '#kernel'，用于切换到 kernel counter 解析）

    Returns:
        NetstatParseResult(cycles=[NetstatCycle(timestamp, interfaces=[...], kernel_counters={...}), ...])
    """
    cycles: list[NetstatCycle] = []
    current_cycle: NetstatCycle | None = None
    current_iface: NetstatInterface | None = None
    # 状态机：
    #   'idle'                  — 还没遇到首个 zzz
    #   'in_interface'          — interface 块中（等待 header/数字行）
    #   'in_interface_rx'       — 刚匹配 RX header，下一数字行是 RX 计数
    #   'in_interface_tx'       — 刚匹配 TX header，下一数字行是 TX 计数
    #   'in_kernel'             — kernel counter 段
    state: str = 'idle'

    if str(filepath).endswith('.gz'):
        f = gzip.open(filepath, mode='rt', encoding='utf-8', errors='replace')
    else:
        f = open(filepath, encoding='utf-8', errors='replace')

    try:
        for raw_line in f:
            line = raw_line.rstrip()

            # 1) cycle 起始行
            m = re.match(r'zzz\s+\*\*\*(.+)', line)
            if m:
                if current_cycle is not None:
                    _finalize(current_cycle, current_iface)
                    cycles.append(current_cycle)
                ts_str = m.group(1).strip()
                dt = _parse_timestamp(ts_str)
                current_cycle = NetstatCycle(
                    timestamp=dt.isoformat() if dt else ts_str,
                )
                current_iface = None
                state = 'in_interface'
                continue

            # 2) 还没遇到 cycle → 跳过（banner、空行、AHF 提示）
            if current_cycle is None:
                continue

            # 3) 段标记行：切到 kernel counter 状态
            if line.strip() == section_marker:
                _finalize(current_cycle, current_iface)
                current_iface = None
                state = 'in_kernel'
                continue

            # 4) interface 块解析
            if state.startswith('in_interface'):
                # interface header：`数字: name: <flags> mtu N qdisc ... state X ...`
                m = INTERFACE_LINE_RE.match(line)
                if m:
                    _finalize(current_cycle, current_iface)
                    ifindex = int(m.group(1))
                    name = m.group(2)
                    flags = m.group(3)
                    mtu = _int_or(MTU_RE.search(line), 1, 0)
                    qdisc = _str_or(QDISC_RE.search(line), 1, '')
                    state_str = _str_or(STATE_RE.search(line), 1, '')
                    mode = _str_or(MODE_RE.search(line), 1, '')
                    master = _str_or(MASTER_RE.search(line), 1, '')
                    current_iface = NetstatInterface(
                        name=name,
                        ifindex=ifindex,
                        flags=flags,
                        mtu=mtu,
                        qdisc=qdisc,
                        state=state_str,
                        mode=mode,
                        master=master,
                    )
                    state = 'in_interface'
                    continue

                # 空行 → interface 块结束
                if not line.strip():
                    if current_iface is not None:
                        _finalize(current_cycle, current_iface)
                        current_iface = None
                    state = 'in_interface'
                    continue

                # link 行：`    link/ether aa:bb:cc:dd:ee:ff brd ...`
                if current_iface is not None and line.strip().startswith('link/'):
                    lm = LINK_RE.search(line)
                    if lm:
                        current_iface.link_type = lm.group(1)
                        current_iface.link_addr = lm.group(2)
                    continue

                # altname 行
                if current_iface is not None and line.strip().startswith('altname '):
                    am = ALTNAME_RE.search(line.strip())
                    if am:
                        current_iface.altname = am.group(1)
                    continue

                # RX header → 下一数字行是 RX
                if RX_HEADER_RE.match(line):
                    state = 'in_interface_rx'
                    continue
                # TX header → 下一数字行是 TX
                if TX_HEADER_RE.match(line):
                    state = 'in_interface_tx'
                    continue

                # 数字行（6 列）— 根据当前 state 决定是 RX 还是 TX
                nm = NUMERIC_RE.match(line)
                if nm and current_iface is not None:
                    nums = [int(g) for g in nm.groups() if g is not None]
                    if len(nums) == 6 and state == 'in_interface_rx':
                        # RX：bytes packets errors dropped missed mcast
                        current_iface.rx_bytes = nums[0]
                        current_iface.rx_packets = nums[1]
                        current_iface.rx_errors = nums[2]
                        current_iface.rx_dropped = nums[3]
                        current_iface.rx_missed = nums[4]
                        current_iface.rx_mcast = nums[5]
                    elif len(nums) == 6 and state == 'in_interface_tx':
                        # TX：bytes packets errors dropped carrier collsns
                        current_iface.tx_bytes = nums[0]
                        current_iface.tx_packets = nums[1]
                        current_iface.tx_errors = nums[2]
                        current_iface.tx_dropped = nums[3]
                        current_iface.tx_carrier = nums[4]
                        current_iface.tx_collsns = nums[5]
                    # 解析完一组数字后回到 in_interface，等待下一个 header
                    state = 'in_interface'
                    continue

                # 其它行 → 跳过
                continue

            # 5) kernel counter 解析
            if state == 'in_kernel':
                # 下一个 zzz 行会被步骤 1 捕获
                km = KERNEL_COUNTER_RE.match(line)
                if km:
                    key = km.group(1)
                    val = int(km.group(2))
                    current_cycle.kernel_counters[key] = val
                continue
    finally:
        f.close()

    _finalize(current_cycle, current_iface)
    if current_cycle is not None:
        cycles.append(current_cycle)

    return NetstatParseResult(cycles=cycles)


def _finalize(cycle: NetstatCycle, iface: NetstatInterface | None) -> None:
    """把当前 iface 存到 cycle.interfaces（转 dict），清空。"""
    if cycle is None or iface is None:
        return
    if iface.name:
        cycle.interfaces.append(_iface_to_dict(iface))


def _iface_to_dict(iface: NetstatInterface) -> dict[str, Any]:
    """dataclass → dict（保持字段名一致）"""
    return {
        'name': iface.name,
        'ifindex': iface.ifindex,
        'flags': iface.flags,
        'mtu': iface.mtu,
        'qdisc': iface.qdisc,
        'state': iface.state,
        'mode': iface.mode,
        'master': iface.master,
        'link_type': iface.link_type,
        'link_addr': iface.link_addr,
        'altname': iface.altname,
        'rx_bytes': iface.rx_bytes,
        'rx_packets': iface.rx_packets,
        'rx_errors': iface.rx_errors,
        'rx_dropped': iface.rx_dropped,
        'rx_missed': iface.rx_missed,
        'rx_mcast': iface.rx_mcast,
        'tx_bytes': iface.tx_bytes,
        'tx_packets': iface.tx_packets,
        'tx_errors': iface.tx_errors,
        'tx_dropped': iface.tx_dropped,
        'tx_carrier': iface.tx_carrier,
        'tx_collsns': iface.tx_collsns,
    }


def _int_or(m: re.Match | None, group: int, default: int) -> int:
    if m is None:
        return default
    try:
        return int(m.group(group))
    except (ValueError, TypeError, IndexError):
        return default


def _str_or(m: re.Match | None, group: int, default: str) -> str:
    if m is None:
        return default
    try:
        return m.group(group) or default
    except (ValueError, TypeError, IndexError):
        return default


def _parse_kernel_counters_from_lines(lines: list[str]) -> dict[str, int]:
    """批量解析 kernel counter 行（保留以便未来调用）。"""
    counters: dict[str, int] = {}
    for line in lines:
        km = KERNEL_COUNTER_RE.match(line)
        if km:
            counters[km.group(1)] = int(km.group(2))
    return counters


def _parse_timestamp(ts_str: str) -> datetime | None:
    """解析 'Mon Jun 15 13:00:04 CST 2026' 这种格式"""
    try:
        ts_clean = re.sub(r'\s+(CST|CDT)\s+', ' ', ts_str)
        return datetime.strptime(ts_clean, '%a %b %d %H:%M:%S %Y')
    except ValueError:
        return None
