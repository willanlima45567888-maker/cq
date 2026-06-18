"""
netstat 工具专用分析器。

输入：v0001 解析器产出的 cycles 列表（每个 cycle 含 interfaces + kernel_counters）。
输出：结构化分析结果（用于前端 Dashboard + Markdown 报告）。

netstat 关注的指标：
  1. 接口流量时序：每个接口的 rx_bytes / tx_bytes / rx_packets / tx_packets
  2. 接口状态汇总：UP / DOWN / UNKNOWN 数量
  3. kernel counter 时序：IP/ICMP/TCP/UDP/IP6/TcpExt/IpExt 关键计数器
  4. 错误率：rx_errors / tx_errors / rx_dropped 趋势
  5. TOP N 接口（按累计流量）
  6. TCP 重传统计（kernel counter TcpRetransSegs）
  7. 结论与建议
"""

from collections import defaultdict
from typing import Any


# ─── 1. 总体概览 ────────────────────────────────────────────

def _build_overview(cycles: list[dict]) -> dict[str, Any]:
    """总体统计：cycle 数 / 时间范围 / 接口汇总 / kernel counter 关键值。"""
    if not cycles:
        return {
            'cycle_count': 0,
            'interface_total': 0,
            'interface_up': 0,
            'interface_down': 0,
            'interface_unknown': 0,
            'interface_names': [],
        }

    # 汇总最后一个 cycle 的接口状态
    last_cycle = cycles[-1]
    interfaces = last_cycle.get('interfaces', [])
    state_count: dict[str, int] = defaultdict(int)
    interface_names: list[str] = []
    for iface in interfaces:
        state_count[iface.get('state', 'UNKNOWN')] += 1
        if iface.get('name'):
            interface_names.append(iface['name'])

    return {
        'cycle_count': len(cycles),
        'interface_total': len(interfaces),
        'interface_up': state_count.get('UP', 0),
        'interface_down': state_count.get('DOWN', 0),
        'interface_unknown': state_count.get('UNKNOWN', 0),
        'interface_names': interface_names,
        'kernel_counter_count': len(last_cycle.get('kernel_counters', {})),
    }


# ─── 2. 接口时序 ────────────────────────────────────────────

INTERFACE_METRICS = [
    ('rx_bytes', 'RX 字节', 'bytes'),
    ('tx_bytes', 'TX 字节', 'bytes'),
    ('rx_packets', 'RX 包数', 'packets'),
    ('tx_packets', 'TX 包数', 'packets'),
    ('rx_errors', 'RX 错误', 'errors'),
    ('tx_errors', 'TX 错误', 'errors'),
    ('rx_dropped', 'RX 丢包', 'dropped'),
    ('tx_dropped', 'TX 丢包', 'dropped'),
]


def _build_interface_trends(cycles: list[dict]) -> dict[str, list]:
    """每个接口的指标时序（跨所有 cycle）。

    Returns:
        {
            'timestamps': [...],
            'rx_bytes': {iface_name: [val_per_cycle], ...},
            'tx_bytes': {...},
            ...
        }
    """
    timestamps: list[str] = []
    # {metric_key: {iface_name: [val_per_cycle]}}
    series: dict[str, dict[str, list]] = {
        key: defaultdict(list) for key, _, _ in INTERFACE_METRICS
    }

    for cyc in cycles:
        timestamps.append(cyc.get('timestamp', ''))
        # 用 (name, ifindex) 作 key — 同名不同 ifindex 当作不同接口
        by_key: dict[str, dict[str, Any]] = {}
        for iface in cyc.get('interfaces', []):
            name = iface.get('name', '')
            if not name:
                continue
            key = f'{name}'
            by_key[key] = iface
        for metric_key, _, _ in INTERFACE_METRICS:
            for iface_key, vals in series[metric_key].items():
                iface = by_key.get(iface_key)
                if iface is not None:
                    vals.append(int(iface.get(metric_key, 0) or 0))
                else:
                    vals.append(0)  # cycle 中无此接口 → 0

    # 转普通 dict（去掉 defaultdict）
    return {
        'timestamps': timestamps,
        **{k: dict(v) for k, v in series.items()},
    }


# ─── 3. Kernel counter 时序 ──────────────────────────────────

# 关注的 kernel counter 关键指标
KERNEL_METRICS = [
    # IP 层
    'IpInReceives', 'IpInDelivers', 'IpOutRequests',
    'IpInDiscards', 'IpOutDiscards', 'IpOutNoRoutes',
    # ICMP
    'IcmpInMsgs', 'IcmpOutMsgs', 'IcmpInErrors', 'IcmpOutErrors',
    # TCP
    'TcpActiveOpens', 'TcpPassiveOpens', 'TcpAttemptFails',
    'TcpEstabResets', 'TcpInSegs', 'TcpOutSegs', 'TcpRetransSegs', 'TcpOutRsts',
    'TcpInErrs', 'TcpInCsumErrors',
    # UDP
    'UdpInDatagrams', 'UdpOutDatagrams', 'UdpNoPorts', 'UdpInErrors',
    # IP6
    'Ip6InReceives', 'Ip6InDelivers', 'Ip6OutRequests',
    # IP 扩展
    'IpExtInOctets', 'IpExtOutOctets',
    'IpExtInNoRoutes', 'IpExtInTruncatedPkts',
    # TCP 扩展
    'TcpExtTCPDelivered', 'TcpExtTCPTimeouts',
    'TcpExtTCPRcvQDrop', 'TcpExtTCPWqueueTooBig',
    'TcpExtTCPAckCompressed', 'TcpExtTCPMTUPSuccess',
]


def _build_kernel_trends(cycles: list[dict]) -> dict[str, list]:
    """关键 kernel counter 时序。

    Returns:
        {
            'timestamps': [...],
            'IpInReceives': [val_per_cycle],
            ...
        }
    """
    timestamps: list[str] = []
    series: dict[str, list] = {k: [] for k in KERNEL_METRICS}

    for cyc in cycles:
        timestamps.append(cyc.get('timestamp', ''))
        kc = cyc.get('kernel_counters', {}) or {}
        for k in KERNEL_METRICS:
            series[k].append(int(kc.get(k, 0) or 0))

    return {
        'timestamps': timestamps,
        **series,
    }


# ─── 4. TOP N 接口（按累计流量）──────────────────────────────

def _build_top_interfaces(cycles: list[dict], top_n: int = 20) -> dict[str, list]:
    """按累计 RX/TX 字节数排序的接口 TOP N。

    累计 = 第一个 cycle 的 bytes（用绝对值，不用差分 — OSW 周期短，丢第一个不影响排序）。
    """
    if not cycles:
        return {'rx_bytes': [], 'tx_bytes': [], 'total_bytes': []}

    # 用每个接口的最后一个 cycle 值（累计流量是 monotonic 增长的）
    last_cycle = cycles[-1]
    stats: list[dict] = []
    for iface in last_cycle.get('interfaces', []):
        name = iface.get('name', '')
        if not name:
            continue
        stats.append({
            'name': name,
            'rx_bytes': int(iface.get('rx_bytes', 0) or 0),
            'tx_bytes': int(iface.get('tx_bytes', 0) or 0),
            'state': iface.get('state', ''),
            'mtu': iface.get('mtu', 0),
        })

    by_rx = sorted(stats, key=lambda x: -x['rx_bytes'])[:top_n]
    by_tx = sorted(stats, key=lambda x: -x['tx_bytes'])[:top_n]
    by_total = sorted(stats, key=lambda x: -(x['rx_bytes'] + x['tx_bytes']))[:top_n]

    return {
        'rx_bytes': by_rx,
        'tx_bytes': by_tx,
        'total_bytes': by_total,
    }


# ─── 5. 接口速率统计（基于首末 cycle 差分）──────────────────

def _build_interface_rates(cycles: list[dict]) -> list[dict]:
    """每个接口的平均速率（基于首末 cycle 差分）。

    避免每个 cycle 都解析（接口表是按 ifindex 顺序稳定的，简化：取 last - first 的差值除以时间）。
    """
    if len(cycles) < 2:
        return []

    first, last = cycles[0], cycles[-1]

    # 用 ifindex → {iface_key: {metric: val}}
    def by_key(cycle: dict) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for iface in cycle.get('interfaces', []):
            name = iface.get('name', '')
            if not name:
                continue
            out[name] = iface
        return out

    first_by = by_key(first)
    last_by = by_key(last)

    rates: list[dict] = []
    for name, last_iface in last_by.items():
        first_iface = first_by.get(name)
        if first_iface is None:
            continue
        # 差分（counter 单调递增，差分即累计增量）
        rx_bytes_delta = int(last_iface.get('rx_bytes', 0) or 0) - int(first_iface.get('rx_bytes', 0) or 0)
        tx_bytes_delta = int(last_iface.get('tx_bytes', 0) or 0) - int(first_iface.get('tx_bytes', 0) or 0)
        rx_packets_delta = int(last_iface.get('rx_packets', 0) or 0) - int(first_iface.get('rx_packets', 0) or 0)
        tx_packets_delta = int(last_iface.get('tx_packets', 0) or 0) - int(first_iface.get('tx_packets', 0) or 0)
        rx_errors_delta = int(last_iface.get('rx_errors', 0) or 0) - int(first_iface.get('rx_errors', 0) or 0)
        tx_errors_delta = int(last_iface.get('tx_errors', 0) or 0) - int(first_iface.get('tx_errors', 0) or 0)
        rx_dropped_delta = int(last_iface.get('rx_dropped', 0) or 0) - int(first_iface.get('rx_dropped', 0) or 0)
        tx_dropped_delta = int(last_iface.get('tx_dropped', 0) or 0) - int(first_iface.get('tx_dropped', 0) or 0)

        rates.append({
            'name': name,
            'state': last_iface.get('state', ''),
            'mtu': last_iface.get('mtu', 0),
            'rx_bytes_delta': rx_bytes_delta,
            'tx_bytes_delta': tx_bytes_delta,
            'rx_packets_delta': rx_packets_delta,
            'tx_packets_delta': tx_packets_delta,
            'rx_errors_delta': rx_errors_delta,
            'tx_errors_delta': tx_errors_delta,
            'rx_dropped_delta': rx_dropped_delta,
            'tx_dropped_delta': tx_dropped_delta,
        })

    # 按总字节数（RX+TX）降序
    rates.sort(key=lambda x: -(x['rx_bytes_delta'] + x['tx_bytes_delta']))
    return rates


# ─── 6. 时间范围 ────────────────────────────────────────────

def _build_time_range(cycles: list[dict]) -> dict[str, str]:
    if not cycles:
        return {'start': '', 'end': ''}
    return {
        'start': cycles[0].get('timestamp', ''),
        'end': cycles[-1].get('timestamp', ''),
    }


# ─── 主分析函数 ──────────────────────────────────────────────

def analyze_cycles(cycles: list) -> dict[str, Any]:
    """单次遍历所有 cycles，返回结构化分析结果。

    Args:
        cycles: v0001 parser 产出的 cycle 列表（每个含 timestamp + interfaces + kernel_counters）。
                支持 NetstatCycle dataclass 和 dict 两种形态。

    Returns:
        dict，字段见各 _build_* 函数的 docstring
    """
    # 把 dataclass 转 dict（保持 interfaces/kernel_counters 子结构）
    norm_cycles: list[dict] = []
    for c in cycles:
        if isinstance(c, dict):
            norm_cycles.append(c)
        else:
            norm_cycles.append({
                'timestamp': c.timestamp,
                'interfaces': c.interfaces,
                'kernel_counters': c.kernel_counters,
            })

    return {
        'overview': _build_overview(norm_cycles),
        'time_range': _build_time_range(norm_cycles),
        'interface_trends': _build_interface_trends(norm_cycles),
        'kernel_trends': _build_kernel_trends(norm_cycles),
        'top_interfaces': _build_top_interfaces(norm_cycles, top_n=20),
        'interface_rates': _build_interface_rates(norm_cycles),
    }
