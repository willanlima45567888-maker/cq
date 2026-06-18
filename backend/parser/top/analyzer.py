"""
top 工具专用分析器。

输入：v0001 解析器产出的 cycles 列表（每个 cycle 含 timestamp + summary + processes）。
输出：分类聚合后的结构化分析结果（用于前端 Dashboard + Markdown 报告）。

top 比 ps 多了系统摘要（uptime/load avg/Tasks/%Cpu/Mem/Swap），所以分析维度更多：
  1. 系统摘要时序：load_avg / tasks_total / cpu_*/ mem_*/ swap_*
  2. 进程分类（同 ps）：总数 / Oracle / Grid / kernel / 用户 / 系统守护 / 用户脚本
  3. CPU TOP N：按 (command, user) 聚合
  4. Memory TOP N：按 RES（KB）聚合
  5. 按用户聚合的进程数时序
  6. 进程状态（R/S/D/Z/T）时序 + 异常检测
  7. 结论与建议

设计原则：单次遍历所有 cycles 完成全部聚合（不二次扫描）。
"""

import re
from collections import defaultdict
from typing import Any


# ─── 复用 ps 的分类规则（ps 的 command 字符串和 top 完全一致）───────

# Kernel 线程：ps 用方括号包裹（[kthreadd]），top 可能用裸名（kthreadd）
# 通过 user=root + command 匹配已知内核线程名来识别
KERNEL_THREAD_NAMES = frozenset({
    'kthreadd', 'kthreadd+kthreadd',  # 旧版偶尔会重复
    'migration', 'ksoftirqd', 'kworker', 'rcu_gp', 'rcu_par_gp', 'rcu_sched', 'rcu_bh',
    'watchdog', 'cpuhp', 'netns', 'kdevtmpfs', 'inet_frag_wq', 'kblockd', 'blkcg_punt_bio',
    'ata_sff', 'md', 'md_bitmap', 'kswapd0', 'kthrotld', 'acpi_thermal_pm',
    'scsi_eh', 'scsi_tmf', 'scsi_timeout', 'ipv6_addrconf', 'kstrp', 'zswap-shrink',
    'kcompactd0', 'slub_flushwq', 'callfunc', 'callfunc_single', 'irq_work', 'lru-add-drain',
    'spi', 'mm_percpu_wq', 'efi_bgrt', 'devfreq_wq', 'kintegrityd', 'xfsalloc',
    'xfs_mru_cache', 'xfs-buf', 'xfs-conv', 'xfs-cil', 'xfs-reclaim', 'xfs-eofblocks',
    'xfs-log', 'xfsaild', 'rpciod', 'xprtiod', 'nfsiod', 'cifsiod', 'smb3decryptd',
    'crypto', 'krfcommd', 'kbase_event', 'pm_wq', 'binder', 'fsnotify_mark',
    'ecryptfs', 'raid5wq', 'dm_bufio_cache', 'dm-thin', 'kdmflush', 'kthrotld',
    'systemd-journald', 'systemd-udevd',  # 这些是用户态 systemd，不算 kernel
})
KERNEL_THREAD_RE = re.compile(r'^\[.+\]$')  # ps 风格（兜底）
KERNEL_COMMAND_RE = re.compile(
    r'^(kthread|kworker|ksoftirqd|migration|rcu_|watchdog|'
    r'cpuhp|netns|kdevtmpfs|inet_frag|kblockd|blkcg_punt|'
    r'ata_sff|kswapd|kthrotld|acpi_thermal|'
    r'scsi_(eh|tmf|timeout)|ipv6_addrconf|kstrp|zswap|kcompactd|slub_flush|'
    r'callfunc|irq_work|lru-add-drain|'
    r'spi|mm_percpu|efi_bgrt|devfreq|kintegrityd|'
    r'xfs|rpciod|xprtiod|nfsiod|cifsiod|smb3decrypt|'
    r'crypto|krfcommd|pm_wq|fsnotify_mark|'
    r'raid5|dm_bufio|dm-thin|kdmflush|kthrotld)',
    re.IGNORECASE,
)

# Oracle 后台进程
ORACLE_RE = re.compile(r'^ora_([a-z]+)\d*|^ora_([a-z]+)_|^J\d{1,3}$|^CJQ\d?$')

# Grid 进程
GRID_RE = re.compile(
    r'^(ocssd|crsd|crsd_|evmd|ohasd|ohasd_|asm_|gipcd|mdnsd|gpnpd|gnsd|osysmond|'
    r'octssd|osbackground|tfa|cha|ohas|diskmon|asmcb|'
    r'oracle\.cha|oracle\.crs|oracle\.css|oracle\.evm)',
)

# Linux 系统进程
SYSTEM_KIND_RE = re.compile(
    r'^(kworker|kthread|ksoftirqd|migration|rcu_|watchdog|'
    r'jbd2/|md\d+_raid|drbd_|multipathd|'
    r'java|systemd|systemd-|udevd|polkitd|chronyd|rsyslogd|'
    r'NetworkManager|sssd|abrt-)',
    re.IGNORECASE,
)

# 已知系统用户
SYSTEM_USERS = frozenset({
    'root', 'bin', 'daemon', 'adm', 'lp', 'sync', 'shutdown', 'halt', 'mail',
    'operator', 'games', 'ftp', 'nobody', 'systemd-network', 'systemd-resolve',
    'systemd-timesync', 'systemd-coredump', 'dbus', 'polkitd', 'sshd', 'ntp',
    'chrony', 'tcpdump', 'rpc', 'rpcuser', 'nfsnobody', 'tss', 'saslauth',
    'postfix', 'mailnull', 'smmsp', 'nginx', 'apache', 'httpd', 'www-data',
    'tomcat', 'mysql', 'mariadb', 'postgres', 'postgresql', 'redis', 'mongodb',
    'zabbix', 'nagios', 'prometheus', 'grafana', 'elasticsearch', 'kibana',
    'rabbitmq', 'haproxy', 'keepalived',
    'docker', 'containerd', 'runc', 'kubelet',
    'oracle', 'grid',  # 这两个单独走 Oracle/Grid 分类
    'avahi', 'colord', 'geoclue', 'rtkit', 'pulse', 'gdm',
    'unbound', 'named', 'dnsmasq',
})

# 用户脚本（basename 命中下列集合）
USER_SCRIPT_BASENAMES = frozenset({
    'raid-check', 'raid_check',
    'rman', 'expdp', 'impdp', 'exp', 'imp',
    'tar', 'gzip', 'gunzip', 'zip', 'unzip',
    'rsync', 'scp', 'rcp', 'cp', 'mv', 'dd',
    'backup.sh', 'backup', 'restore.sh',
    'ssh', 'ssh-keygen',
    'reboot', 'shutdown', 'yum', 'dnf', 'apt', 'apt-get', 'rpm',
    'crontab', 'at', 'anacron',
})


def _cmd_basename(command: str) -> str:
    """提取 command 的程序名（兼容 /path/to/foo -arg1 -arg2）"""
    if not command:
        return ''
    parts = command.split()
    first = parts[0]
    shell_prefixes = ('/bin/sh', '/bin/bash', '/bin/dash', '/usr/bin/env')
    if first in shell_prefixes and len(parts) >= 2:
        return parts[1].rstrip('/').split('/')[-1]
    base = first.rstrip('/').split('/')[-1]
    if ':' in base:
        base = base.split(':', 1)[0]
    return base


def _classify_process(p: dict) -> str:
    """单个进程分类：oracle / grid / kernel / user / system_daemon / user_script"""
    cmd = p.get('command', '').strip()
    user = p.get('user', '').strip()
    if not cmd:
        return 'system_daemon'
    if KERNEL_THREAD_RE.match(cmd):
        return 'kernel'
    # top 风格：裸名（无方括号），通过已知内核线程名模式识别
    if user == 'root' and KERNEL_COMMAND_RE.match(cmd.split()[0] if cmd else ''):
        return 'kernel'
    if ORACLE_RE.match(cmd):
        return 'oracle'
    if GRID_RE.match(cmd) or user == 'grid':
        return 'grid'
    base = _cmd_basename(cmd)
    if base in USER_SCRIPT_BASENAMES:
        return 'user_script'
    if user in SYSTEM_USERS:
        return 'system_daemon'
    return 'user'


# ─── 主分析函数 ──────────────────────────────────────────────

def _cycle_dict(c) -> dict:
    """归一化 TopCycle dataclass / dict 到 dict。"""
    if isinstance(c, dict):
        return c
    return c.__dict__ if hasattr(c, '__dict__') else {}


def analyze_cycles(cycles: list) -> dict[str, Any]:
    """单次遍历所有 cycles，返回结构化分析结果。

    Args:
        cycles: v0001 parser 产出的 cycle 列表（每个含 timestamp + summary + processes）。
                支持 TopCycle dataclass 和 dict 两种形态。

    Returns:
        dict, 字段见各 _build_* 函数的 docstring
    """
    # 把 dataclass 转 dict（保持 summary 子结构嵌套）
    norm_cycles: list[dict] = []
    for c in cycles:
        if isinstance(c, dict):
            norm_cycles.append(c)
        else:
            s = c.summary
            d = {
                'timestamp': c.timestamp,
                'processes': [p if isinstance(p, dict) else p.__dict__ for p in c.processes],
                'summary': s.__dict__ if hasattr(s, '__dict__') else (s if isinstance(s, dict) else {}),
            }
            norm_cycles.append(d)

    return {
        'overview': _build_overview(norm_cycles),
        'system_trends': _build_system_trends(norm_cycles),
        'cpu_top': _build_cpu_top(norm_cycles, top_n=20),
        'mem_top': _build_mem_top(norm_cycles, top_n=20),
        'process_categories': _build_process_categories(norm_cycles),
        'user_distribution': _build_user_distribution(norm_cycles),
        'state_trends': _build_state_trends(norm_cycles),
        'program_cpu_timeline': _build_program_cpu_timeline(norm_cycles, top_n=20),
        'time_range': _build_time_range(norm_cycles),
    }


# ─── 1. 总体概览 ────────────────────────────────────────────

def _build_overview(cycles: list[dict]) -> dict[str, Any]:
    """总体统计：cycle 数 / 时间范围 / 平均 load / 进程分类计数。"""
    total_procs = 0
    counts = {'total': 0, 'oracle': 0, 'grid': 0, 'kernel': 0,
              'user': 0, 'system_daemon': 0, 'user_script': 0}
    user_counts: dict[str, int] = defaultdict(int)
    pid_user_seen: set[tuple[int, str]] = set()

    load_1m_max = 0.0
    cpu_us_max = 0.0
    cpu_wa_max = 0.0

    for cyc in cycles:
        for p in cyc.get('processes', []):
            cat = _classify_process(p)
            counts[cat] += 1
            counts['total'] += 1
            user = p.get('user', '').strip()
            pid = p.get('pid', 0)
            key = (pid, user)
            if key not in pid_user_seen:
                user_counts[user] += 1
                pid_user_seen.add(key)
        total_procs += len(cyc.get('processes', []))

        s = cyc.get('summary') or {}
        load_1m_max = max(load_1m_max, float(s.get('load_avg_1m') or 0.0))
        cpu_us_max = max(cpu_us_max, float(s.get('cpu_us') or 0.0))
        cpu_wa_max = max(cpu_wa_max, float(s.get('cpu_wa') or 0.0))

    by_user = [
        {'user': u, 'process_count': c}
        for u, c in sorted(user_counts.items(), key=lambda kv: -kv[1])
    ]

    return {
        'cycle_count': len(cycles),
        'total_procs': total_procs,
        'load_1m_max': round(load_1m_max, 2),
        'cpu_us_max': round(cpu_us_max, 2),
        'cpu_wa_max': round(cpu_wa_max, 2),
        **counts,
        'by_user': by_user,
    }


# ─── 2. 系统摘要时序 ─────────────────────────────────────────

def _build_system_trends(cycles: list[dict]) -> dict[str, list]:
    """每个 cycle 的系统摘要时序数据。"""
    timestamps: list[str] = []
    load_1m: list[float] = []
    load_5m: list[float] = []
    load_15m: list[float] = []
    tasks_total: list[int] = []
    tasks_running: list[int] = []
    tasks_sleeping: list[int] = []
    tasks_stopped: list[int] = []
    tasks_zombie: list[int] = []
    cpu_us: list[float] = []
    cpu_sy: list[float] = []
    cpu_ni: list[float] = []
    cpu_id: list[float] = []
    cpu_wa: list[float] = []
    cpu_hi: list[float] = []
    cpu_si: list[float] = []
    cpu_st: list[float] = []
    mem_total: list[float] = []
    mem_used: list[float] = []
    mem_free: list[float] = []
    mem_buff: list[float] = []
    mem_pct: list[float] = []  # mem_used / mem_total
    swap_total: list[float] = []
    swap_used: list[float] = []
    avail_mem: list[float] = []

    for cyc in cycles:
        ts = cyc.get('timestamp', '')
        s = cyc.get('summary') or {}
        timestamps.append(ts)

        load_1m.append(float(s.get('load_avg_1m') or 0.0))
        load_5m.append(float(s.get('load_avg_5m') or 0.0))
        load_15m.append(float(s.get('load_avg_15m') or 0.0))

        tasks_total.append(int(s.get('tasks_total') or 0))
        tasks_running.append(int(s.get('tasks_running') or 0))
        tasks_sleeping.append(int(s.get('tasks_sleeping') or 0))
        tasks_stopped.append(int(s.get('tasks_stopped') or 0))
        tasks_zombie.append(int(s.get('tasks_zombie') or 0))

        cpu_us.append(float(s.get('cpu_us') or 0.0))
        cpu_sy.append(float(s.get('cpu_sy') or 0.0))
        cpu_ni.append(float(s.get('cpu_ni') or 0.0))
        cpu_id.append(float(s.get('cpu_id') or 0.0))
        cpu_wa.append(float(s.get('cpu_wa') or 0.0))
        cpu_hi.append(float(s.get('cpu_hi') or 0.0))
        cpu_si.append(float(s.get('cpu_si') or 0.0))
        cpu_st.append(float(s.get('cpu_st') or 0.0))

        mt = float(s.get('mem_total_mib') or 0.0)
        mu = float(s.get('mem_used_mib') or 0.0)
        mem_total.append(mt)
        mem_used.append(mu)
        mem_free.append(float(s.get('mem_free_mib') or 0.0))
        mem_buff.append(float(s.get('mem_buff_cache_mib') or 0.0))
        mem_pct.append(round(mu / mt * 100, 2) if mt > 0 else 0.0)

        st = float(s.get('swap_total_mib') or 0.0)
        su = float(s.get('swap_used_mib') or 0.0)
        swap_total.append(st)
        swap_used.append(su)
        avail_mem.append(float(s.get('avail_mem_mib') or 0.0))

    return {
        'timestamps': timestamps,
        'load_1m': load_1m,
        'load_5m': load_5m,
        'load_15m': load_15m,
        'tasks_total': tasks_total,
        'tasks_running': tasks_running,
        'tasks_sleeping': tasks_sleeping,
        'tasks_stopped': tasks_stopped,
        'tasks_zombie': tasks_zombie,
        'cpu_us': cpu_us,
        'cpu_sy': cpu_sy,
        'cpu_ni': cpu_ni,
        'cpu_id': cpu_id,
        'cpu_wa': cpu_wa,
        'cpu_hi': cpu_hi,
        'cpu_si': cpu_si,
        'cpu_st': cpu_st,
        'mem_total': mem_total,
        'mem_used': mem_used,
        'mem_free': mem_free,
        'mem_buff': mem_buff,
        'mem_pct': mem_pct,
        'swap_total': swap_total,
        'swap_used': swap_used,
        'avail_mem': avail_mem,
    }


# ─── 3. CPU TOP N ─────────────────────────────────────────

def _build_cpu_top(cycles: list[dict], top_n: int) -> list[dict]:
    """按 (command, user) 聚合 CPU% 占用 Top N。"""
    stats: dict[tuple[str, str], dict] = {}

    for cyc in cycles:
        ts = cyc.get('timestamp', '')
        for p in cyc.get('processes', []):
            cmd = p.get('command', '').strip()
            if not cmd:
                continue
            user = p.get('user', '').strip()
            cpu = p.get('cpu_pct', 0.0) or 0.0
            pid = p.get('pid', 0)
            key = (cmd, user)
            if key not in stats:
                stats[key] = {
                    'command': cmd,
                    'user': user,
                    'pid': pid,
                    'cpu_pct_max': 0.0,
                    'cpu_pct_sum': 0.0,
                    'cycles_seen': 0,
                    'first_seen': ts,
                    'last_seen': ts,
                    'res_kb_max': 0,
                    'state': '',
                }
            s = stats[key]
            s['cpu_pct_max'] = max(s['cpu_pct_max'], cpu)
            s['cpu_pct_sum'] += cpu
            s['cycles_seen'] += 1
            s['res_kb_max'] = max(s['res_kb_max'], int(p.get('res_kb') or 0))
            # 主导状态（取出现次数最多的）
            state = p.get('s', '')
            if state:
                s.setdefault('_state_count', defaultdict(int))
                s['_state_count'][state] += 1
            if ts < s['first_seen']:
                s['first_seen'] = ts
            if ts > s['last_seen']:
                s['last_seen'] = ts

    sorted_stats = sorted(
        stats.values(),
        key=lambda s: (-s['cpu_pct_max'], -s['cycles_seen']),
    )

    result = []
    for s in sorted_stats[:top_n]:
        avg = s['cpu_pct_sum'] / s['cycles_seen'] if s['cycles_seen'] else 0.0
        # 主导状态
        sc = s.get('_state_count') or {}
        dom_state = max(sc.items(), key=lambda kv: kv[1])[0] if sc else 'S'
        result.append({
            'command': s['command'],
            'user': s['user'],
            'pid': s['pid'],
            'cpu_pct_max': round(s['cpu_pct_max'], 2),
            'cpu_pct_avg': round(avg, 2),
            'cycles_seen': s['cycles_seen'],
            'first_seen': s['first_seen'],
            'last_seen': s['last_seen'],
            'res_kb_max': s['res_kb_max'],
            'state': dom_state,
        })
    return result


# ─── 4. Memory TOP N ───────────────────────────────────────

def _build_mem_top(cycles: list[dict], top_n: int) -> list[dict]:
    """按 (command, user) 聚合 RES（KB）占用 Top N。"""
    stats: dict[tuple[str, str], dict] = {}

    for cyc in cycles:
        ts = cyc.get('timestamp', '')
        for p in cyc.get('processes', []):
            cmd = p.get('command', '').strip()
            if not cmd:
                continue
            user = p.get('user', '').strip()
            res = int(p.get('res_kb') or 0)
            if res == 0:
                continue
            virt = int(p.get('virt_kb') or 0)
            pid = p.get('pid', 0)
            cpu = float(p.get('cpu_pct') or 0.0)
            key = (cmd, user)
            if key not in stats:
                stats[key] = {
                    'command': cmd,
                    'user': user,
                    'pid': pid,
                    'res_kb_max': 0,
                    'res_kb_sum': 0,
                    'virt_kb_max': 0,
                    'cycles_seen': 0,
                    'cpu_pct_max': 0.0,
                    'cpu_pct_sum': 0.0,
                    'first_seen': ts,
                    'last_seen': ts,
                    'state': '',
                }
            s = stats[key]
            s['res_kb_max'] = max(s['res_kb_max'], res)
            s['res_kb_sum'] += res
            s['virt_kb_max'] = max(s['virt_kb_max'], virt)
            s['cycles_seen'] += 1
            s['cpu_pct_max'] = max(s['cpu_pct_max'], cpu)
            s['cpu_pct_sum'] += cpu
            state = p.get('s', '')
            if state:
                s.setdefault('_state_count', defaultdict(int))
                s['_state_count'][state] += 1
            if ts < s['first_seen']:
                s['first_seen'] = ts
            if ts > s['last_seen']:
                s['last_seen'] = ts

    sorted_stats = sorted(
        stats.values(),
        key=lambda s: (-s['res_kb_max'], -s['cycles_seen']),
    )

    result = []
    for s in sorted_stats[:top_n]:
        avg_res = s['res_kb_sum'] / s['cycles_seen'] if s['cycles_seen'] else 0
        avg_cpu = s['cpu_pct_sum'] / s['cycles_seen'] if s['cycles_seen'] else 0.0
        sc = s.get('_state_count') or {}
        dom_state = max(sc.items(), key=lambda kv: kv[1])[0] if sc else 'S'
        result.append({
            'command': s['command'],
            'user': s['user'],
            'pid': s['pid'],
            'res_kb_max': s['res_kb_max'],
            'res_kb_avg': int(avg_res),
            'virt_kb_max': s['virt_kb_max'],
            'cycles_seen': s['cycles_seen'],
            'cpu_pct_max': round(s['cpu_pct_max'], 2),
            'cpu_pct_avg': round(avg_cpu, 2),
            'first_seen': s['first_seen'],
            'last_seen': s['last_seen'],
            'state': dom_state,
        })
    return result


# ─── 5. 进程分类时序（同 ps 的 trends 字段）───────────────────

def _build_process_categories(cycles: list[dict]) -> dict[str, list]:
    """每个 cycle 的分类计数时序数据。"""
    timestamps: list[str] = []
    total: list[int] = []
    oracle: list[int] = []
    grid: list[int] = []
    kernel: list[int] = []
    user: list[int] = []
    system_daemon: list[int] = []
    user_script: list[int] = []

    for cyc in cycles:
        ts = cyc.get('timestamp', '')
        procs = cyc.get('processes', [])
        timestamps.append(ts)
        c_total = c_oracle = c_grid = c_kernel = c_user = c_system = c_script = 0
        for p in procs:
            cat = _classify_process(p)
            c_total += 1
            if cat == 'oracle': c_oracle += 1
            elif cat == 'grid': c_grid += 1
            elif cat == 'kernel': c_kernel += 1
            elif cat == 'user': c_user += 1
            elif cat == 'user_script': c_script += 1
            else: c_system += 1
        total.append(c_total)
        oracle.append(c_oracle)
        grid.append(c_grid)
        kernel.append(c_kernel)
        user.append(c_user)
        system_daemon.append(c_system)
        user_script.append(c_script)

    return {
        'timestamps': timestamps,
        'total': total,
        'oracle': oracle,
        'grid': grid,
        'kernel': kernel,
        'user': user,
        'system_daemon': system_daemon,
        'user_script': user_script,
    }


# ─── 6. 按用户分布（用户进程数时序）────────────────────────

def _build_user_distribution(cycles: list[dict], top_n: int = 10) -> dict[str, Any]:
    """按用户的进程数时序数据。

    Returns:
      {
        'users': [{user, total, avg, max}, ...]   # Top N 用户
        'by_cycle': [{timestamp, user1: count, ...}, ...]
        'top_n': int
      }
    """
    # user -> cycle -> count
    user_cycle_counts: dict[str, list[int]] = defaultdict(list)
    all_users: set[str] = set()

    for cyc in cycles:
        per_user: dict[str, int] = defaultdict(int)
        for p in cyc.get('processes', []):
            u = p.get('user', '').strip() or '(empty)'
            per_user[u] += 1
            all_users.add(u)
        for u in all_users:
            user_cycle_counts[u].append(per_user.get(u, 0))
        for u in per_user:
            if u not in user_cycle_counts:
                user_cycle_counts[u] = [0] * (len(cycles) - 1) + [per_user[u]]
            elif len(user_cycle_counts[u]) < len(cycles):
                user_cycle_counts[u].append(per_user[u])

    # 按累计出现次数排序，取 Top N
    users_sorted = sorted(
        all_users,
        key=lambda u: sum(user_cycle_counts[u]),
        reverse=True,
    )
    top_users = users_sorted[:top_n]

    users_summary = []
    for u in top_users:
        counts = user_cycle_counts[u]
        users_summary.append({
            'user': u,
            'total': sum(counts),
            'avg': round(sum(counts) / len(counts), 1) if counts else 0.0,
            'max': max(counts) if counts else 0,
        })

    by_cycle = []
    for i, cyc in enumerate(cycles):
        row: dict[str, Any] = {'timestamp': cyc.get('timestamp', '')}
        for u in top_users:
            row[u] = user_cycle_counts[u][i] if i < len(user_cycle_counts[u]) else 0
        by_cycle.append(row)

    return {
        'users': users_summary,
        'by_cycle': by_cycle,
        'top_n': top_n,
    }


# ─── 7. 进程状态时序 ──────────────────────────────────────

def _build_state_trends(cycles: list[dict]) -> dict[str, Any]:
    """进程状态（R/S/D/Z/T/I）时序 + 异常检测。"""
    state_order = ['R', 'S', 'D', 'Z', 'T', 'I']
    state_legend = {
        'R': 'Running（运行中）',
        'S': 'Sleeping（睡眠，可中断）',
        'D': 'Disk Sleep（不可中断睡眠，IO 阻塞）',
        'Z': 'Zombie（僵尸）',
        'T': 'Stopped（停止）',
        'I': 'Idle（空闲，RHEL 8+ 内核线程）',
    }
    by_cycle: list[dict] = []
    total_by_state: dict[str, int] = defaultdict(int)
    current: dict[str, int] = {}
    max_d = 0
    max_z = 0
    max_r = 0
    long_d_pids: list[dict] = []  # 长期处于 D 状态的进程
    zombie_pids: list[dict] = []  # 出现过 Z 状态的进程

    # 跟踪 PID 状态：pid -> (first_seen, last_seen, cycles_in_d, cycles_in_z, user, command)
    pid_state_track: dict[int, dict] = {}
    last_summary_d = 0
    last_summary_z = 0

    for cyc in cycles:
        ts = cyc.get('timestamp', '')
        cycle_state: dict[str, int] = {s: 0 for s in state_order}
        seen_pids: set[int] = set()

        for p in cyc.get('processes', []):
            s_char = p.get('s', '').strip() or 'S'
            if s_char not in state_order:
                s_char = 'S'
            cycle_state[s_char] += 1
            total_by_state[s_char] += 1

            pid = int(p.get('pid') or 0)
            if pid > 0:
                seen_pids.add(pid)
                if pid not in pid_state_track:
                    pid_state_track[pid] = {
                        'user': p.get('user', '').strip(),
                        'command': p.get('command', '').strip(),
                        'first_seen': ts,
                        'last_seen': ts,
                        'cycles_d': 0,
                        'cycles_z': 0,
                    }
                t = pid_state_track[pid]
                t['last_seen'] = ts
                if s_char == 'D':
                    t['cycles_d'] += 1
                if s_char == 'Z':
                    t['cycles_z'] += 1

        max_d = max(max_d, cycle_state['D'])
        max_z = max(max_z, cycle_state['Z'])
        max_r = max(max_r, cycle_state['R'])
        current = cycle_state

        row = {'timestamp': ts, **cycle_state}
        by_cycle.append(row)

    # 长期 D 状态：在超过 50% 的 cycle 中处于 D
    cycle_count = len(cycles)
    if cycle_count > 0:
        threshold = max(1, cycle_count // 2)
        for pid, t in pid_state_track.items():
            if t['cycles_d'] >= threshold:
                long_d_pids.append({
                    'pid': pid,
                    'user': t['user'],
                    'command': t['command'],
                    'first_seen': t['first_seen'],
                    'last_seen': t['last_seen'],
                    'cycles_d': t['cycles_d'],
                })
            if t['cycles_z'] >= threshold:
                zombie_pids.append({
                    'pid': pid,
                    'user': t['user'],
                    'command': t['command'],
                    'first_seen': t['first_seen'],
                    'last_seen': t['last_seen'],
                    'cycles_z': t['cycles_z'],
                })

    return {
        'by_cycle': by_cycle,
        'total_by_state': dict(total_by_state),
        'current': current,
        'max_d': max_d,
        'max_z': max_z,
        'max_r': max_r,
        'long_d_pids': long_d_pids[:20],  # 限制返回数
        'zombie_pids': zombie_pids[:20],
        'state_order': state_order,
        'state_legend': state_legend,
    }


# ─── 8. 进程 CPU 时序（按程序聚合）─────────────────────────

def _build_program_cpu_timeline(cycles: list[dict], top_n: int = 20) -> dict[str, Any]:
    """按 command 聚合每个 cycle 的 CPU% 总和（跨所有用户/PID），取 top N。

    设计要点：
      - 同 command 多进程时 CPU% 求和（如 4 个 gzip × 100% = 400%，反映"该程序占用了多少核"）
      - top N 按整个时间段的累计 CPU 用量降序（高 CPU 程序优先）
      - by_cycle 只包含 top N 的命令（缺失 cycle 填 0），控制响应大小

    Returns:
      {
        'programs': [{command, total_cpu, cycles_seen, avg_cpu}, ...],   # Top N 命令
        'by_cycle': [{timestamp, cmd1: sum, cmd2: sum, ...}, ...],        # 每个 cycle 累计 CPU%
        'top_n': int,
      }
    """
    cmd_totals: dict[str, float] = defaultdict(float)
    cmd_counts: dict[str, int] = defaultdict(int)
    by_cycle_full: list[dict[str, Any]] = []

    for cyc in cycles:
        ts = cyc.get('timestamp', '')
        per_cmd: dict[str, float] = defaultdict(float)
        for p in cyc.get('processes', []):
            cmd = p.get('command', '').strip()
            if not cmd:
                continue
            cpu = float(p.get('cpu_pct') or 0.0)
            if cpu == 0.0:
                continue
            per_cmd[cmd] += cpu
            cmd_totals[cmd] += cpu
            cmd_counts[cmd] += 1
        by_cycle_full.append({'timestamp': ts, **per_cmd})

    # 选 top N（按总 CPU 降序）
    sorted_cmds = sorted(cmd_totals.items(), key=lambda kv: -kv[1])
    top_cmds = [c for c, _ in sorted_cmds[:top_n]]

    programs_summary = []
    for cmd in top_cmds:
        total = cmd_totals[cmd]
        seen = cmd_counts[cmd]
        programs_summary.append({
            'command': cmd,
            'total_cpu': round(total, 2),
            'cycles_seen': seen,
            'avg_cpu': round(total / seen, 2) if seen else 0.0,
        })

    # by_cycle 只保留 top N 命令（缺失填 0）
    by_cycle_filtered: list[dict[str, Any]] = []
    for row in by_cycle_full:
        filtered: dict[str, Any] = {'timestamp': row['timestamp']}
        for cmd in top_cmds:
            filtered[cmd] = round(float(row.get(cmd, 0)), 2)
        by_cycle_filtered.append(filtered)

    return {
        'programs': programs_summary,
        'by_cycle': by_cycle_filtered,
        'top_n': top_n,
    }


# ─── 9. 时间范围 ──────────────────────────────────────────

def _build_time_range(cycles: list[dict]) -> dict[str, str]:
    if not cycles:
        return {'start': '', 'end': ''}
    return {
        'start': cycles[0].get('timestamp', ''),
        'end': cycles[-1].get('timestamp', ''),
    }


# ─── 10. 按 "TOP 5 出现次数" 排序的程序 TOP N ─────────────────────
# 不同于 _build_cpu_top/_build_mem_top（按峰值 max 排序），这里统计
# "该程序在多少个 cycle 出现在该指标 TOP 5 之前"，反映持续占用，
# 比单点峰值更能说明"长期在抢资源的程序"。
#
# 排序键：top5_count desc → cycles_seen desc → max 降序
# 输出字段与 _build_cpu_top/_build_mem_top 兼容，多一个 top5_count 字段。

def _build_top_by_top5_count(
    cycles: list[dict],
    top_n: int,
    metric_field: str,  # 'cpu_pct' 或 'mem_pct'
) -> list[dict]:
    """按 (metric_field) 在每个 cycle TOP 5 出现次数排序的程序 TOP N。"""
    # 第一遍：每个 cycle 的 metric_field 前 5 名（用 pid+command+user 作 key）
    cycle_top5: list[set] = []
    for cyc in cycles:
        procs = cyc.get('processes', []) or []
        procs_sorted = sorted(
            procs,
            key=lambda p: -float(p.get(metric_field) or 0),
        )
        s5: set = set()
        for p in procs_sorted[:5]:
            pid = int(p.get('pid') or 0)
            cmd = str(p.get('command') or '').strip()
            user = str(p.get('user') or '').strip()
            s5.add((pid, cmd, user))
        cycle_top5.append(s5)

    # 第二遍：按 (command, user) 聚合，统计 top5 出现次数
    stats: dict[tuple[str, str], dict] = {}
    for cyc_idx, cyc in enumerate(cycles):
        top5_set = cycle_top5[cyc_idx]
        procs = cyc.get('processes', []) or []
        ts = cyc.get('timestamp', '')
        for p in procs:
            pid = int(p.get('pid') or 0)
            cmd = str(p.get('command') or '').strip()
            user = str(p.get('user') or '').strip()
            if (pid, cmd, user) not in top5_set:
                continue
            k = (cmd, user)
            if k not in stats:
                stats[k] = {
                    'command': cmd,
                    'user': user,
                    'pid': pid,
                    'top5_count': 0,
                    'cycles_seen': 0,
                    'first_seen': ts,
                    'last_seen': ts,
                    # cpu_pct 聚合
                    'cpu_pct_sum': 0.0,
                    'cpu_pct_max': 0.0,
                    # mem_pct 聚合
                    'mem_pct_sum': 0.0,
                    'mem_pct_max': 0.0,
                    # 物理内存
                    'res_kb_sum': 0,
                    'res_kb_max': 0,
                    'virt_kb_max': 0,
                    'state': '',
                }
            s = stats[k]
            s['top5_count'] += 1
            s['cycles_seen'] += 1
            cpu = float(p.get('cpu_pct') or 0)
            mem = float(p.get('mem_pct') or 0)
            res_kb = int(p.get('res_kb') or 0)
            s['cpu_pct_sum'] += cpu
            s['cpu_pct_max'] = max(s['cpu_pct_max'], cpu)
            s['mem_pct_sum'] += mem
            s['mem_pct_max'] = max(s['mem_pct_max'], mem)
            s['res_kb_sum'] += res_kb
            s['res_kb_max'] = max(s['res_kb_max'], res_kb)
            s['virt_kb_max'] = max(s['virt_kb_max'], int(p.get('virt_kb') or 0))
            state = str(p.get('s') or '').strip()
            if state:
                s.setdefault('_state_count', {})
                s['_state_count'][state] = s['_state_count'].get(state, 0) + 1
            if ts < s['first_seen']:
                s['first_seen'] = ts
            if ts > s['last_seen']:
                s['last_seen'] = ts

    # 排序：top5_count desc → cycles_seen desc → cpu_pct_max desc
    sorted_stats = sorted(
        stats.values(),
        key=lambda s: (-s['top5_count'], -s['cycles_seen'], -s['cpu_pct_max']),
    )

    result: list[dict] = []
    for s in sorted_stats[:top_n]:
        cpu_avg = s['cpu_pct_sum'] / s['cycles_seen'] if s['cycles_seen'] else 0.0
        mem_avg = s['mem_pct_sum'] / s['cycles_seen'] if s['cycles_seen'] else 0.0
        res_avg = s['res_kb_sum'] // s['cycles_seen'] if s['cycles_seen'] else 0
        sc = s.get('_state_count') or {}
        dom_state = max(sc.items(), key=lambda kv: kv[1])[0] if sc else 'S'
        result.append({
            'command': s['command'],
            'user': s['user'],
            'pid': s['pid'],
            'top5_count': s['top5_count'],
            'cycles_seen': s['cycles_seen'],
            'first_seen': s['first_seen'],
            'last_seen': s['last_seen'],
            'cpu_pct_max': round(s['cpu_pct_max'], 2),
            'cpu_pct_avg': round(cpu_avg, 2),
            'mem_pct_max': round(s['mem_pct_max'], 2),
            'mem_pct_avg': round(mem_avg, 2),
            'res_kb_max': s['res_kb_max'],
            'res_kb_avg': res_avg,
            'virt_kb_max': s['virt_kb_max'],
            'state': dom_state,
        })
    return result


def _build_cpu_top_by_top5(cycles: list[dict], top_n: int = 20) -> list[dict]:
    """按 cpu_pct 在每个 cycle TOP 5 出现次数排序的程序 TOP N。"""
    return _build_top_by_top5_count(cycles, top_n, 'cpu_pct')


def _build_mem_top_by_top5(cycles: list[dict], top_n: int = 20) -> list[dict]:
    """按 mem_pct 在每个 cycle TOP 5 出现次数排序的程序 TOP N。"""
    return _build_top_by_top5_count(cycles, top_n, 'mem_pct')
