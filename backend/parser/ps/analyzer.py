"""
ps 工具专用分析器。

输入：v0001 解析器产出的 cycles 列表（每个 cycle 含 timestamp + processes 列表）。
输出：分类聚合后的结构化分析结果（用于前端 Dashboard + Markdown 报告）。

关注维度（按 spec）：
  1. 进程基础信息（总数 / Oracle / Grid / 用户 / kernel）
  2. 资源消耗（CPU TOP N / Memory TOP N）
  3. Oracle 后台进程（pmon/lgwr/dbw/ckpt/mman/mmon + PX 并行 + Job 队列）
  4. Grid 基础设施（ocssd/crsd/evmd/ohasd/asm_pmon）
  5. Linux 系统进程（kworker/jbd2/md/drbd/multipathd/java/systemd）
  6. 用户脚本（raid-check/rman/expdp/impdp/tar/gzip/rsync/scp/backup.sh）
  7. 生命周期（首现/末现/重启次数）— 用于甘特图

设计原则：
  - 单次遍历所有 cycles 完成全部聚合（不二次扫描）
  - 分类用正则前缀匹配，不用 fuzzy match（速度优先）
  - 不修改 v0001 parser，本模块独立可测
"""

import re
from collections import defaultdict
from typing import Any


# ─── 分类规则 ──────────────────────────────────────────────────

# Kernel 线程：ps 中以方括号包裹，如 [kthreadd] / [migration/0] / [kworker/0:0]
KERNEL_THREAD_RE = re.compile(r'^\[.+\]$')

# Oracle 后台进程（按 COMMAND 前缀匹配 SID 后的下划线变体也兼容）
#  - ora_pmon_<sid>, ora_lgwr, ora_dbw0, ora_dbw1, ...
#  - ora_ckpt, ora_mman, ora_mmon, ora_mmnl
#  - ora_smon, ora_reco, ora_qmn*, ora_vktm, ora_lmon, ora_lmd0
#  - ora_p000..p999  （PX 并行）
#  - ora_pr00..pr99  （parallel recovery）
#  - ora_dia0, ora_m000 (mmon slave), ora_s000 (shared server)
#  - J000..J999      （job slave，CJQ0 调度）
#  - CJQ0            （job queue coordinator）
ORACLE_RE = re.compile(r'^ora_([a-z]+)\d*|^ora_([a-z]+)_|^J\d{1,3}$|^CJQ\d?$')

# Oracle 子分类（按上面正则的捕获组映射）
ORACLE_BG_KIND_RE = re.compile(
    r'^ora_(pmon|lgwr|dbw\d*|ckpt|mman|mmon|mmnl|smon|reco|qmn\d*|vktm|'
    r'lmon|lmd\d*|lck\d*|rms\d*|rvwr|arc\d*|tt\d*|dia\d*|m000|s\d{3}|n\d{3})'
)
ORACLE_PX_RE = re.compile(r'^ora_p\d{3}')
ORACLE_PR_RE = re.compile(r'^ora_pr\d{2}')
ORACLE_JOB_RE = re.compile(r'^J\d{1,3}$')
ORACLE_JOB_COORD_RE = re.compile(r'^CJQ\d?$')

# Grid 进程：按 command 前缀
GRID_RE = re.compile(
    r'^(ocssd|crsd|crsd_|evmd|ohasd|ohasd_|asm_|gipcd|mdnsd|gpnpd|gnsd|osysmond|'
    r'octssd|osbackground|tfa|cha|ohas|diskmon|asmcb|'
    r'oracle\.cha|oracle\.crs|oracle\.css|oracle\.evm)',
)

# Grid 子分类（用于详细表）
GRID_KIND_RE = re.compile(
    r'^(ocssd|crsd|crsd_|evmd|ohasd|ohasd_|asm_pmon|asm_([a-z]+)|gipcd|mdnsd|gpnpd|'
    r'gnsd|osysmond|octssd|diskmon|tfa|cha)'
)

# Linux 系统进程
SYSTEM_KIND_RE = re.compile(
    r'^(kworker|kthread|ksoftirqd|migration|rcu_|watchdog|'
    r'jbd2/|md\d+_raid|drbd_|multipathd|'
    r'java|systemd|systemd-|udevd|polkitd|chronyd|rsyslogd|'
    r'NetworkManager|sssd|abrt-)',
    re.IGNORECASE,
)

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

# 已知系统用户（用于区分"系统守护进程"和"人类用户"）
# uid 通常 < 1000 的系统服务账号 + 常见监控/守护进程用户
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
    'oracle', 'grid',  # 这两个单独走 Oracle/Grid 分类，不算 system
    'avahi', 'colord', 'geoclue', 'rtkit', 'pulse', 'gdm',
    'unbound', 'named', 'dnsmasq',
})

# 内部辅助：取 command 的 basename（兼容 /path/to/foo -arg1 -arg2）
def _cmd_basename(command: str) -> str:
    """提取 command 的"程序名"用于脚本识别。

    规则：
      - /opt/oracle/product/19c/bin/rman target /  →  rman
      - tar -czf /tmp/x.tar.gz /data                 →  tar
      - /bin/sh ./backup.sh                         →  sh（注意不是 backup.sh）
      - sshd: sendoh@notty                          →  sshd
    """
    if not command:
        return ''
    # 跳过前导的 /bin/sh /bin/bash /usr/bin/python 等解释器（脚本本体在第一个参数里）
    # 但若 cmd 以 shell 解释器开头且有后续参数，取第一个参数
    parts = command.split()
    first = parts[0]
    # 解释器链：/bin/sh ./backup.sh
    shell_prefixes = ('/bin/sh', '/bin/bash', '/bin/dash', '/usr/bin/env')
    if first in shell_prefixes and len(parts) >= 2:
        return parts[1].rstrip('/').split('/')[-1]
    # 普通情况：取路径最后一段
    base = first.rstrip('/').split('/')[-1]
    # 处理 "sshd: sendoh@notty" 这种带冒号的（ps 把 argv[0] 后的都展开了）
    if ':' in base:
        base = base.split(':', 1)[0]
    return base


# ─── 主分析函数 ──────────────────────────────────────────────

def _cycle_dict(c) -> dict:
    """归一化 PsCycle dataclass / dict 到 dict。

    PsCycle 是 dataclass（有 timestamp/processes 属性），
    cache 里读出来的是 dict。分析器只关心 dict 接口。
    """
    if isinstance(c, dict):
        return c
    return c.__dict__ if hasattr(c, '__dict__') else {}


def analyze_cycles(cycles: list) -> dict[str, Any]:
    """单次遍历所有 cycles，返回结构化分析结果。

    Args:
        cycles: v0001 parser 产出的 cycle 列表（每个含 timestamp + processes）。
                支持 PsCycle dataclass 和 dict 两种形态。

    Returns:
        dict, 字段见各 _build_* 函数的 docstring
    """
    cycles = [_cycle_dict(c) for c in cycles]
    return {
        'overview': _build_overview(cycles),
        'trends': _build_trends(cycles),
        'cpu_top': _enrich_top_entries(cycles, _build_cpu_top(cycles, top_n=20)),
        'mem_top': _enrich_top_entries(cycles, _build_mem_top(cycles, top_n=20)),
        'oracle': _build_oracle(cycles),
        'grid': _build_grid(cycles),
        'system': _build_system(cycles),
        'user_scripts': _build_user_scripts(cycles),
        'lifecycle': _build_lifecycle(cycles),
        'state': _build_state_analysis(cycles),
        'wchan': _build_wchan_analysis(cycles),
        'user_trends': _build_user_trends(cycles, top_n_per_user=10),
        'time_range': _build_time_range(cycles),
    }


# ─── 1. 总体概览 ────────────────────────────────────────────

def _build_overview(cycles: list[dict]) -> dict[str, Any]:
    """总体统计：总数 / Oracle / Grid / 用户 / kernel / 系统守护。

    分类逻辑：
      - kernel:  command 匹配 ^\\[.*\\]$
      - oracle:  command 匹配 ^ora_.* 或 ^J\\d+$ 或 ^CJQ\\d?$
      - grid:    command 匹配 grid 前缀 或 user == 'grid' 且 command 不属于上述
      - user:    username 不在 SYSTEM_USERS 里（视为人类交互用户）
      - system_daemon: 剩下的
    """
    counts: dict[str, int] = {
        'total': 0,
        'oracle': 0,
        'grid': 0,
        'kernel': 0,
        'user': 0,
        'system_daemon': 0,
        'user_script': 0,  # 单独跟踪（不计入 spec 的 5 分类，但前端可展示）
    }
    # 按用户聚合进程数（仅最近 cycle 还是全 cycle？spec 要"总体统计表"，全 cycle 累计）
    user_counts: dict[str, int] = defaultdict(int)
    pid_user_seen: set[tuple[int, str]] = set()  # 去重：(pid, user)

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

    # 按进程数降序排列的用户列表
    by_user = [
        {'user': u, 'process_count': c}
        for u, c in sorted(user_counts.items(), key=lambda kv: -kv[1])
    ]

    return {
        **counts,
        'by_user': by_user,
    }


# ─── 2. 趋势数据（每个 cycle 一行）───────────────────────

def _build_trends(cycles: list[dict]) -> dict[str, list]:
    """每个 cycle 的分类计数时序数据。

    用于前端画：
      - 进程总数趋势
      - Oracle/PX/Job 趋势
    """
    timestamps: list[str] = []
    total: list[int] = []
    oracle: list[int] = []
    grid: list[int] = []
    kernel: list[int] = []
    user: list[int] = []
    system_daemon: list[int] = []
    user_script: list[int] = []
    px: list[int] = []
    job: list[int] = []

    for cyc in cycles:
        ts = cyc.get('timestamp', '')
        procs = cyc.get('processes', [])
        timestamps.append(ts)

        c_total = 0
        c_oracle = 0
        c_grid = 0
        c_kernel = 0
        c_user = 0
        c_system = 0
        c_script = 0
        c_px = 0
        c_job = 0

        for p in procs:
            cat = _classify_process(p)
            c_total += 1
            if cat == 'oracle':
                c_oracle += 1
                # 进一步计 PX 和 Job
                cmd = p.get('command', '').strip()
                if ORACLE_PX_RE.match(cmd):
                    c_px += 1
                if ORACLE_JOB_RE.match(cmd) or ORACLE_JOB_COORD_RE.match(cmd):
                    c_job += 1
            elif cat == 'grid':
                c_grid += 1
            elif cat == 'kernel':
                c_kernel += 1
            elif cat == 'user':
                c_user += 1
            elif cat == 'user_script':
                c_script += 1
            else:
                c_system += 1

        total.append(c_total)
        oracle.append(c_oracle)
        grid.append(c_grid)
        kernel.append(c_kernel)
        user.append(c_user)
        system_daemon.append(c_system)
        user_script.append(c_script)
        px.append(c_px)
        job.append(c_job)

    return {
        'timestamps': timestamps,
        'total': total,
        'oracle': oracle,
        'grid': grid,
        'kernel': kernel,
        'user': user,
        'system_daemon': system_daemon,
        'user_script': user_script,
        'px': px,
        'job': job,
    }


# ─── 3. CPU TOP N ─────────────────────────────────────────

def _build_cpu_top(cycles: list[dict], top_n: int) -> list[dict]:
    """按 command 聚合 CPU 占用 Top N。

    每个 entry:
      - command:  完整命令
      - user:     进程所有者
      - pid:      代表 PID（首次出现的 PID）
      - cpu_pct_max:  所有 cycle 中的最大 CPU%
      - cpu_pct_avg:  所有出现 cycle 的平均 CPU%
      - cycles_seen:  出现在多少个 cycle 中
      - first_seen:   首次出现的时间
      - last_seen:    最后出现的时间
    """
    stats: dict[tuple[str, str], dict] = {}  # (command, user) -> stats

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
                }
            s = stats[key]
            s['cpu_pct_max'] = max(s['cpu_pct_max'], cpu)
            s['cpu_pct_sum'] += cpu
            s['cycles_seen'] += 1
            if ts < s['first_seen']:
                s['first_seen'] = ts
            if ts > s['last_seen']:
                s['last_seen'] = ts

    # 排序：先按 cpu_pct_max 降序，再按 cycles_seen 降序（持续高 CPU > 偶发尖峰）
    sorted_stats = sorted(
        stats.values(),
        key=lambda s: (-s['cpu_pct_max'], -s['cycles_seen']),
    )

    result = []
    for s in sorted_stats[:top_n]:
        avg = s['cpu_pct_sum'] / s['cycles_seen'] if s['cycles_seen'] else 0.0
        result.append({
            'command': s['command'],
            'user': s['user'],
            'pid': s['pid'],
            'cpu_pct_max': round(s['cpu_pct_max'], 2),
            'cpu_pct_avg': round(avg, 2),
            'cycles_seen': s['cycles_seen'],
            'first_seen': s['first_seen'],
            'last_seen': s['last_seen'],
        })
    return result


# ─── 4. Memory TOP N ───────────────────────────────────────

def _build_mem_top(cycles: list[dict], top_n: int) -> list[dict]:
    """按 command 聚合 RSS（KB）占用 Top N。"""
    stats: dict[tuple[str, str], dict] = {}

    for cyc in cycles:
        ts = cyc.get('timestamp', '')
        for p in cyc.get('processes', []):
            cmd = p.get('command', '').strip()
            if not cmd:
                continue
            user = p.get('user', '').strip()
            rss = p.get('rss', 0) or 0
            vsz = p.get('vsz', 0) or 0
            pid = p.get('pid', 0)
            key = (cmd, user)
            if key not in stats:
                stats[key] = {
                    'command': cmd,
                    'user': user,
                    'pid': pid,
                    'rss_max_kb': 0,
                    'rss_sum_kb': 0,
                    'vsz_max_kb': 0,
                    'cycles_seen': 0,
                    'first_seen': ts,
                    'last_seen': ts,
                }
            s = stats[key]
            s['rss_max_kb'] = max(s['rss_max_kb'], rss)
            s['rss_sum_kb'] += rss
            s['vsz_max_kb'] = max(s['vsz_max_kb'], vsz)
            s['cycles_seen'] += 1
            if ts < s['first_seen']:
                s['first_seen'] = ts
            if ts > s['last_seen']:
                s['last_seen'] = ts

    sorted_stats = sorted(
        stats.values(),
        key=lambda s: (-s['rss_max_kb'], -s['cycles_seen']),
    )

    result = []
    for s in sorted_stats[:top_n]:
        avg = s['rss_sum_kb'] / s['cycles_seen'] if s['cycles_seen'] else 0
        result.append({
            'command': s['command'],
            'user': s['user'],
            'pid': s['pid'],
            'rss_max_kb': s['rss_max_kb'],
            'rss_avg_kb': int(avg),
            'vsz_max_kb': s['vsz_max_kb'],
            'cycles_seen': s['cycles_seen'],
            'first_seen': s['first_seen'],
            'last_seen': s['last_seen'],
        })
    return result


# ─── 5. Oracle 后台进程分析 ────────────────────────────────

def _build_oracle(cycles: list[dict]) -> dict[str, Any]:
    """Oracle 后台进程分类统计 + PX/Job 峰值。

    返回:
      - background_counts: {kind: max_concurrent}，kind ∈ pmon/lgwr/dbw/ckpt/...
      - background_by_cycle: [{ts, pmon, lgwr, ...}]   每个 cycle 的数量
      - px_peak / job_peak: 整段时间内的最大并发
      - px_trend:            [{ts, count}]  PX 并行数随时间变化
      - distinct_pids_pmon/lgwr/...:  累计出现过的不同 PID 数（用于检测重启）
    """
    # 每个 cycle 的各类后台进程数
    # m/s/n 三个 kind 是从 m000/s000/n000 剥后缀得到的（MMON slave / Shared Server / Connection Broker）
    kinds = ('pmon', 'lgwr', 'dbw', 'ckpt', 'mman', 'mmon', 'smon', 'reco',
             'qmn', 'vktm', 'lmon', 'lmd', 'lck', 'rms', 'rvwr',
             'arc', 'tt', 'dia', 'm', 's', 'n',
             'px', 'pr', 'job', 'other')
    by_cycle: list[dict] = []
    distinct_pids: dict[str, set] = {k: set() for k in kinds}
    px_peak = 0
    job_peak = 0

    for cyc in cycles:
        ts = cyc.get('timestamp', '')
        procs = cyc.get('processes', [])
        counts = {k: 0 for k in kinds}
        px_count = 0
        job_count = 0

        for p in procs:
            cmd = p.get('command', '').strip()
            user = p.get('user', '').strip()
            if user != 'oracle' and not ORACLE_RE.match(cmd):
                continue
            kind = _oracle_kind(cmd)
            if kind:
                counts[kind] += 1
                distinct_pids[kind].add(p.get('pid', 0))
            if ORACLE_PX_RE.match(cmd):
                px_count += 1
            if ORACLE_JOB_RE.match(cmd) or ORACLE_JOB_COORD_RE.match(cmd):
                job_count += 1

        row = {'timestamp': ts, **counts}
        by_cycle.append(row)
        px_peak = max(px_peak, px_count)
        job_peak = max(job_peak, job_count)

    # 取每种 kind 在所有 cycle 里的最大并发数
    background_counts = {
        k: max((row[k] for row in by_cycle), default=0) for k in kinds
    }
    # 转 int 兼容 JSON
    distinct_pids_count = {k: len(v) for k, v in distinct_pids.items() if v}

    return {
        'background_counts': background_counts,
        'background_by_cycle': by_cycle,
        'px_peak': px_peak,
        'job_peak': job_peak,
        'distinct_pids': distinct_pids_count,
    }


def _oracle_kind(command: str) -> str:
    """返回 Oracle 后台进程的具体类型（短名）。不匹配则返回空字符串。

    规范化规则：去掉匹配组里的后缀数字（arc3 → arc、lck0 → lck、tt00 → tt、m000 → m）。
    """
    if not command:
        return ''
    m = ORACLE_BG_KIND_RE.match(command)
    if m:
        full = m.group(1)
        # 去掉后缀数字
        base = re.sub(r'\d+$', '', full)
        # mmnl 也归到 mman 一类
        if base == 'mmnl':
            return 'mman'
        return base
    # PX/parallel recovery
    if ORACLE_PX_RE.match(command):
        return 'px'
    if ORACLE_PR_RE.match(command):
        return 'pr'
    # Job
    if ORACLE_JOB_RE.match(command) or ORACLE_JOB_COORD_RE.match(command):
        return 'job'
    # 兜底：仍属于 Oracle 进程的（ora_* 但未识别）
    if command.startswith('ora_'):
        return 'other'
    return ''


# ─── 6. Grid Infrastructure 分析 ───────────────────────────

def _build_grid(cycles: list[dict]) -> dict[str, Any]:
    """Grid 进程统计 + 异常检测。

    返回:
      - kind_counts: {kind: max_concurrent}，kind ∈ ocssd/crsd/evmd/ohasd/asm_pmon/...
      - kind_by_cycle: [{ts, ...}]
      - abnormal_exit:   [{name, last_seen, was_kind}] 突然消失的进程
      - distinct_pids:   {kind: count}  累计不同 PID
    """
    # 主要 Grid 进程类型
    kinds = ('ocssd', 'crsd', 'evmd', 'ohasd', 'asm_pmon', 'gipcd', 'mdnsd',
             'gpnpd', 'gnsd', 'osysmond', 'cha', 'other_grid')
    by_cycle: list[dict] = []
    distinct_pids: dict[str, set] = {k: set() for k in kinds}

    # 跟踪每个 Grid 进程上一次出现的时间（异常退出检测）
    # 用 (pid, kind) 做 key；如果上次在，下一次不在了，且后续 cycles 都没再出现 → 异常退出
    last_seen: dict[tuple[int, str], str] = {}  # (pid, kind) -> last ts
    pid_to_kind: dict[int, str] = {}  # pid -> kind（首次出现时记录）

    for cyc in cycles:
        ts = cyc.get('timestamp', '')
        procs = cyc.get('processes', [])
        counts = {k: 0 for k in kinds}
        present_pids: set[tuple[int, str]] = set()

        for p in procs:
            user = p.get('user', '').strip()
            cmd = p.get('command', '').strip()
            if user != 'grid' and not GRID_RE.match(cmd):
                continue
            kind = _grid_kind(cmd)
            if not kind:
                continue
            counts[kind] += 1
            pid = p.get('pid', 0)
            distinct_pids[kind].add(pid)
            if pid not in pid_to_kind:
                pid_to_kind[pid] = kind
            present_pids.add((pid, kind))
            last_seen[(pid, kind)] = ts

        by_cycle.append({'timestamp': ts, **counts})

    # 异常退出检测：每种 kind 跟踪其 PID 历史
    # - kind 出现 > 1 个 PID → 有过重启（restart_count = pid 数 - 1）
    # - 不再上报"abnormal_exit"（无可靠基准，单一 PID 消失可能是重启而非异常）
    kind_counts = {
        k: max((row[k] for row in by_cycle), default=0) for k in kinds
    }
    distinct_pids_count = {k: len(v) for k, v in distinct_pids.items() if v}
    restart_count = {k: max(0, len(v) - 1) for k, v in distinct_pids.items() if v}

    return {
        'kind_counts': kind_counts,
        'kind_by_cycle': by_cycle,
        'distinct_pids': distinct_pids_count,
        'restart_count': restart_count,
    }


def _grid_kind(command: str) -> str:
    """返回 Grid 进程的具体类型（短名）。不匹配则返回空字符串。

    两路判定：
      1. COMMAND 前缀匹配（ocssd.bin / crsd / asm_pmon / ...）
      2. Java 进程（grid user 跑 java ... 后面带 oracle.cha/oracle.crs/oracle.css/oracle.evm）
    """
    if not command:
        return ''
    m = GRID_KIND_RE.match(command)
    if m:
        full = m.group(1)
        # asm_pmon_*, asm_cb*, asm_*: 都归 asm_pmon
        if full.startswith('asm_'):
            return 'asm_pmon'
        if full.startswith('crsd') or full.startswith('crsd_'):
            return 'crsd'
        if full.startswith('ohasd') or full.startswith('ohasd_'):
            return 'ohasd'
        if full == 'cha' or full == 'tfa':
            return 'cha' if full == 'cha' else 'tfa'
        return full  # ocssd / evmd / gipcd / mdnsd / gpnpd / gnsd / osysmond
    # 兜底：Java-based Grid 进程（OSW 里的 oracle.cha.server.CHADDriver 之类）
    if 'oracle.cha' in command:
        return 'cha'
    if 'oracle.crs' in command:
        return 'crsd'
    if 'oracle.css' in command:
        return 'ocssd'
    if 'oracle.evm' in command:
        return 'evmd'
    return ''


# ─── 7. Linux 系统进程分析 ─────────────────────────────────

def _build_system(cycles: list[dict]) -> dict[str, Any]:
    """Linux 系统进程分类统计。

    返回:
      - kind_counts:   {kind: avg_count} 各类系统进程平均数量
      - kind_peak:     {kind: max_count} 各类系统进程峰值
      - kind_cycles:   {kind: cycles_seen} 各类进程出现在多少 cycle 中
    """
    kinds = ('kworker', 'jbd2', 'md_raid', 'drbd', 'multipathd', 'java',
             'systemd', 'other_system')
    sum_counts: dict[str, int] = {k: 0 for k in kinds}
    peak_counts: dict[str, int] = {k: 0 for k in kinds}
    cycle_counts: dict[str, int] = {k: 0 for k in kinds}

    n_cycles = 0
    for cyc in cycles:
        n_cycles += 1
        procs = cyc.get('processes', [])
        seen_kinds: set[str] = set()
        per_kind = {k: 0 for k in kinds}

        for p in procs:
            user = p.get('user', '').strip()
            cmd = p.get('command', '').strip()
            # 系统进程：root 或匹配 SYSTEM_KIND_RE（kworker 即使在 root 也算）
            if user != 'root' and not SYSTEM_KIND_RE.match(cmd):
                continue
            kind = _system_kind(cmd)
            if not kind:
                continue
            per_kind[kind] += 1
            seen_kinds.add(kind)

        for k in kinds:
            sum_counts[k] += per_kind[k]
            peak_counts[k] = max(peak_counts[k], per_kind[k])
        for k in seen_kinds:
            cycle_counts[k] += 1

    avg_counts = {k: round(sum_counts[k] / n_cycles, 1) for k in kinds} if n_cycles else {}
    return {
        'kind_avg': avg_counts,
        'kind_peak': peak_counts,
        'kind_cycles': cycle_counts,
        'cycle_count': n_cycles,
    }


def _system_kind(command: str) -> str:
    """返回 Linux 系统进程的具体类型。"""
    if not command:
        return ''
    # kernel 线程方括号形式已在 overview 单独计，这里跳过
    if KERNEL_THREAD_RE.match(command):
        return ''
    if command.startswith('kworker') or command.startswith('kthread') \
            or command.startswith('ksoftirqd') or command.startswith('migration') \
            or command.startswith('rcu_') or command.startswith('watchdog'):
        return 'kworker'
    if command.startswith('jbd2/'):
        return 'jbd2'
    if command.startswith('md') and '_raid' in command:
        return 'md_raid'
    if command.startswith('drbd_'):
        return 'drbd'
    if command.startswith('multipathd'):
        return 'multipathd'
    if command.startswith('java') or '/java' in command:
        return 'java'
    if command.startswith('systemd'):
        return 'systemd'
    # 兜底：command 走 SYSTEM_KIND_RE 匹配但未细分的，归 other_system
    if SYSTEM_KIND_RE.match(command):
        return 'other_system'
    return ''


# ─── 8. 用户脚本识别 ───────────────────────────────────────

def _build_user_scripts(cycles: list[dict]) -> list[dict]:
    """识别用户脚本（raid-check/rman/expdp/...）的执行记录。

    返回: [{ name, count, first_seen, last_seen, max_cpu, max_rss_kb, runs }]
      - name: 脚本名（如 rman / expdp / backup.sh）
      - count: 总出现次数
      - runs:  [{pid, first_seen, last_seen, max_cpu, max_rss_kb}] 每次执行的记录
              通过 PID 变化识别"新一次执行"
    """
    # 用 (basename, pid) 分组；同 basename 不同 pid = 不同执行
    runs_data: dict[str, dict[int, dict]] = defaultdict(dict)
    # 跟踪每个 basename 当前所有 live PID（用于 PID 复用 vs 新一次执行的简单启发）
    for cyc in cycles:
        ts = cyc.get('timestamp', '')
        for p in cyc.get('processes', []):
            cmd = p.get('command', '').strip()
            if not cmd:
                continue
            base = _cmd_basename(cmd)
            if base not in USER_SCRIPT_BASENAMES:
                continue
            pid = p.get('pid', 0)
            cpu = p.get('cpu_pct', 0.0) or 0.0
            rss = p.get('rss', 0) or 0
            if pid not in runs_data[base]:
                runs_data[base][pid] = {
                    'pid': pid,
                    'first_seen': ts,
                    'last_seen': ts,
                    'max_cpu': cpu,
                    'max_rss_kb': rss,
                    'command_sample': cmd[:200],
                }
            r = runs_data[base][pid]
            r['last_seen'] = ts
            r['max_cpu'] = max(r['max_cpu'], cpu)
            r['max_rss_kb'] = max(r['max_rss_kb'], rss)

    result = []
    for name, pids in sorted(runs_data.items()):
        runs = sorted(pids.values(), key=lambda r: r['first_seen'])
        # 持续时间：如果 first_seen == last_seen，只出现 1 个 cycle
        all_first = min(r['first_seen'] for r in runs)
        all_last = max(r['last_seen'] for r in runs)
        result.append({
            'name': name,
            'run_count': len(runs),
            'first_seen': all_first,
            'last_seen': all_last,
            'max_cpu': round(max(r['max_cpu'] for r in runs), 2),
            'max_rss_kb': max(r['max_rss_kb'] for r in runs),
            'runs': runs[:50],  # 限制最多 50 条
        })
    # 按首次出现时间升序
    result.sort(key=lambda x: x['first_seen'])
    return result


def _build_user_trends(cycles: list[dict], top_n_per_user: int = 10) -> dict[str, Any]:
    """按用户的进程数时序数据。

    返回:
      - users:         [{user, total, avg, max}]   TOP N 用户（按累计进程数降序）
      - by_cycle:      [{timestamp, user1: count, user2: count, ...}]
                       每个 cycle 一行，每列是一个 user 的进程数
      - top_n:         int  返回的用户数
    """
    if not cycles:
        return {'users': [], 'by_cycle': [], 'top_n': 0}

    # 第一次扫描：累计每个 user 在所有 cycle 中出现的次数（用于排序 + 决定 top_n）
    user_totals: dict[str, int] = defaultdict(int)
    for cyc in cycles:
        for p in cyc.get('processes', []):
            u = (p.get('user', '') or '').strip()
            if u:
                user_totals[u] += 1

    # 选 top_n 用户（按累计出现次数降序）
    top_users = [u for u, _ in sorted(user_totals.items(), key=lambda kv: -kv[1])[:top_n_per_user]]
    if not top_users:
        return {'users': [], 'by_cycle': [], 'top_n': 0}
    top_set = set(top_users)

    # 第二次扫描：每个 cycle 统计这些用户的进程数
    by_cycle: list[dict] = []
    for cyc in cycles:
        ts = cyc.get('timestamp', '')
        row: dict = {'timestamp': ts}
        for u in top_users:
            row[u] = 0
        for p in cyc.get('processes', []):
            u = (p.get('user', '') or '').strip()
            if u in top_set:
                row[u] += 1
        by_cycle.append(row)

    # 摘要：每个用户的 累计 / 平均 / 峰值
    users_summary: list[dict] = []
    for u in top_users:
        arr = [row.get(u, 0) for row in by_cycle]
        users_summary.append({
            'user': u,
            'total': sum(arr),
            'avg': round(sum(arr) / len(arr), 1) if arr else 0,
            'max': max(arr) if arr else 0,
        })

    return {
        'users': users_summary,
        'by_cycle': by_cycle,
        'top_n': len(top_users),
    }


# ─── 10. 进程状态分析 ─────────────────────────────────────

# ps 中常见的进程状态（man ps）：
#   R  running 或 runnable（在运行队列上）
#   S  interruptible sleep（可中断睡眠，等待事件完成）
#   D  uninterruptible sleep（不可中断睡眠，通常等待 I/O）
#   Z  zombie（已终止但未被父进程收割）
#   T  stopped（被信号停止，如 SIGSTOP）
#   I  idle（内核空闲线程，2.6.33+）
#   X  dead（极少见）
STATE_LEGEND: dict[str, str] = {
    'R': 'Running',
    'S': 'Sleeping',
    'D': 'Uninterruptible',
    'Z': 'Zombie',
    'T': 'Stopped',
    'I': 'Idle',
    'X': 'Dead',
}
# 状态在趋势图中的展示顺序（重要的在前）
STATE_DISPLAY_ORDER: tuple[str, ...] = ('R', 'S', 'D', 'Z', 'T', 'I', 'X')


def _build_state_analysis(cycles: list[dict]) -> dict[str, Any]:
    """进程状态分析：每个 cycle 的 R/S/D/Z 数量 + 趋势 + 异常进程。

    返回:
      - by_cycle:    [{timestamp, R, S, D, Z, T, I, X}]  每个 cycle 的状态计数
      - total_by_state: {state: total_count}           全周期累加
      - current:      {state: count}                   最后一个 cycle 的状态
      - max_z:        int                              Z 峰值（出现 zombie 最多的 cycle）
      - max_d:        int                              D 峰值（I/O 阻塞峰值）
      - zombie_pids:  [{pid, user, command, first_seen, last_seen, cycles_z}] 持续 Z 的进程
      - long_d_pids:  [{pid, user, command, first_seen, last_seen, cycles_d}] 持续 D 的进程
    """
    by_cycle: list[dict] = []
    total_by_state: dict[str, int] = {s: 0 for s in STATE_DISPLAY_ORDER}
    # 跟踪每个 PID 的状态历史（用于检测"持续 Z"和"持续 D"）
    # pid -> {state: count, total: count, first_seen, last_seen, user, command}
    pid_state: dict[int, dict] = {}

    for cyc in cycles:
        ts = cyc.get('timestamp', '')
        procs = cyc.get('processes', [])
        counts = {s: 0 for s in STATE_DISPLAY_ORDER}
        for p in procs:
            # 状态字段可能含 '+' / '<' / '>' 等修饰（高优先级、前台等）
            # 例如 R+, S<, S<s 等。取首字母
            raw_state = (p.get('s', '') or '').strip().upper()
            st = raw_state[0] if raw_state else ''
            if st not in STATE_DISPLAY_ORDER:
                # 未知状态，归为 'S'（最常见）
                st = 'S'
            counts[st] += 1
            total_by_state[st] += 1
            pid = p.get('pid', 0)
            if pid:
                if pid not in pid_state:
                    pid_state[pid] = {
                        'states': {},
                        'total': 0,
                        'first_seen': ts,
                        'last_seen': ts,
                        'user': p.get('user', ''),
                        'command': p.get('command', ''),
                    }
                rec = pid_state[pid]
                rec['states'][st] = rec['states'].get(st, 0) + 1
                rec['total'] += 1
                if ts < rec['first_seen']:
                    rec['first_seen'] = ts
                if ts > rec['last_seen']:
                    rec['last_seen'] = ts
        by_cycle.append({'timestamp': ts, **counts})

    # 当前（最后一个 cycle）状态
    current = by_cycle[-1] if by_cycle else {s: 0 for s in STATE_DISPLAY_ORDER}
    current_clean = {s: current.get(s, 0) for s in STATE_DISPLAY_ORDER}

    # 峰值
    max_z = max((row.get('Z', 0) for row in by_cycle), default=0)
    max_d = max((row.get('D', 0) for row in by_cycle), default=0)
    max_r = max((row.get('R', 0) for row in by_cycle), default=0)

    # 异常检测：
    # - 持续 Z（PID 在 ≥ 3 个 cycle 都处于 Z 状态）
    # - 持续 D（PID 在 ≥ 10 个 cycle 都处于 D 状态）
    zombie_pids: list[dict] = []
    long_d_pids: list[dict] = []
    for pid, rec in pid_state.items():
        z_cnt = rec['states'].get('Z', 0)
        d_cnt = rec['states'].get('D', 0)
        if z_cnt >= 3 and z_cnt == rec['total']:  # 全部 cycle 都是 Z
            zombie_pids.append({
                'pid': pid,
                'user': rec['user'],
                'command': rec['command'],
                'first_seen': rec['first_seen'],
                'last_seen': rec['last_seen'],
                'cycles_z': z_cnt,
            })
        elif d_cnt >= 10 and d_cnt == rec['total']:  # 全部 cycle 都是 D
            long_d_pids.append({
                'pid': pid,
                'user': rec['user'],
                'command': rec['command'],
                'first_seen': rec['first_seen'],
                'last_seen': rec['last_seen'],
                'cycles_d': d_cnt,
            })

    # 排序 + 限制
    zombie_pids.sort(key=lambda x: -x['cycles_z'])
    long_d_pids.sort(key=lambda x: -x['cycles_d'])
    zombie_pids = zombie_pids[:50]
    long_d_pids = long_d_pids[:50]

    # 过滤 total_by_state 中为 0 的项
    total_clean = {s: v for s, v in total_by_state.items() if v > 0}

    return {
        'by_cycle': by_cycle,
        'total_by_state': total_clean,
        'current': current_clean,
        'max_z': max_z,
        'max_d': max_d,
        'max_r': max_r,
        'zombie_pids': zombie_pids,
        'long_d_pids': long_d_pids,
        'state_order': list(STATE_DISPLAY_ORDER),
        'state_legend': STATE_LEGEND,
    }


# ─── 9. 生命周期（甘特图数据）────────────────────────────

def _build_lifecycle(cycles: list[dict]) -> list[dict]:
    """每个重要进程的首次/末次出现时间 + PID 重启次数 + 运行时长。

    返回: [{ name, category, first_seen, last_seen, pid_count,
             duration_seconds, cycles_seen, frequency_pct, pids }]
      - name: 进程展示名（规范化后的）
      - category: oracle / grid / system / script
      - pid_count: 该进程名累计出现过的不同 PID 数
      - duration_seconds: 首次出现 → 最后出现的时长（秒）
      - cycles_seen: 出现在多少个 cycle 中
      - frequency_pct: cycles_seen / 总 cycle 数 × 100
      - pids: [{pid, first_seen, last_seen}]  各 PID 的出现区间

    只跟踪"重要"进程：
      - Oracle 后台（ora_*）
      - Grid 进程（ocssd/crsd/evmd/ohasd/asm_pmon/...）
      - 系统守护（kworker/jbd2/multipathd/java/systemd）
      - 用户脚本（USER_SCRIPT_BASENAMES）
    """
    # key = (canonical_name, category)
    # pid -> (first_seen, last_seen)
    name_pids: dict[tuple[str, str], dict[int, list[str]]] = {}
    name_cycles: dict[tuple[str, str], set[str]] = {}  # 记录每个进程出现在哪些 cycle

    for cyc in cycles:
        ts = cyc.get('timestamp', '')
        for p in cyc.get('processes', []):
            name, category = _lifecycle_name(p)
            if not name or not category:
                continue
            pid = p.get('pid', 0)
            key = (name, category)
            if key not in name_pids:
                name_pids[key] = {}
                name_cycles[key] = set()
            if pid not in name_pids[key]:
                name_pids[key][pid] = [ts, ts]
            else:
                if ts < name_pids[key][pid][0]:
                    name_pids[key][pid][0] = ts
                if ts > name_pids[key][pid][1]:
                    name_pids[key][pid][1] = ts
            name_cycles[key].add(ts)

    total_cycles = len(cycles)
    result = []
    for (name, category), pids in name_pids.items():
        pid_list = [
            {'pid': pid, 'first_seen': r[0], 'last_seen': r[1]}
            for pid, r in pids.items()
        ]
        all_first = min(r[0] for r in pids.values())
        all_last = max(r[1] for r in pids.values())
        # 计算时长
        dur_sec = _parse_duration_seconds(all_first, all_last)
        cycles_seen = len(name_cycles[key])
        freq = (cycles_seen / total_cycles * 100) if total_cycles else 0
        result.append({
            'name': name,
            'category': category,
            'first_seen': all_first,
            'last_seen': all_last,
            'pid_count': len(pids),
            'pids': pid_list,
            'duration_seconds': dur_sec,
            'cycles_seen': cycles_seen,
            'frequency_pct': round(freq, 1),
        })

    # 按 duration 降序，再按 category 优先 + name
    cat_order = {'oracle': 0, 'grid': 1, 'system': 2, 'script': 3}
    result.sort(key=lambda x: (-x['duration_seconds'], cat_order.get(x['category'], 99), x['name']))
    return result


def _parse_duration_seconds(first_ts: str, last_ts: str) -> float:
    """解析两个 ISO 时间戳之差（秒）。失败返回 0。"""
    from datetime import datetime
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S'):
        try:
            t1 = datetime.strptime(first_ts[:19], fmt)
            t2 = datetime.strptime(last_ts[:19], fmt)
            return (t2 - t1).total_seconds()
        except (ValueError, TypeError):
            continue
    return 0.0


def _lifecycle_name(proc: dict) -> tuple[str, str]:
    """返回 (display_name, category)。不属于"重要进程"则返回 ('', '')。"""
    user = proc.get('user', '').strip()
    cmd = proc.get('command', '').strip()
    if not cmd:
        return '', ''

    # 1. Oracle
    if ORACLE_RE.match(cmd) or (user == 'oracle' and cmd.startswith('oracle')):
        return cmd, 'oracle'

    # 2. Grid
    if user == 'grid' or GRID_RE.match(cmd):
        return cmd, 'grid'

    # 3. 系统守护
    if user == 'root' and SYSTEM_KIND_RE.match(cmd):
        return cmd, 'system'

    # 4. 用户脚本
    base = _cmd_basename(cmd)
    if base in USER_SCRIPT_BASENAMES:
        return cmd, 'script'

    return '', ''


# ─── 10. 时间范围 ──────────────────────────────────────────

def _build_time_range(cycles: list[dict]) -> dict[str, str]:
    if not cycles:
        return {'start': '', 'end': ''}
    return {
        'start': cycles[0].get('timestamp', ''),
        'end': cycles[-1].get('timestamp', ''),
    }


# ─── 进程分类辅助 ──────────────────────────────────────────

def _classify_process(proc: dict) -> str:
    """返回单个进程的分类标签。

    分类（互斥优先级）：
      kernel > oracle > grid > user_script > user > system_daemon
    """
    user = proc.get('user', '').strip()
    cmd = proc.get('command', '').strip()
    if not cmd:
        return 'system_daemon'

    # 1. kernel 线程
    if KERNEL_THREAD_RE.match(cmd):
        return 'kernel'

    # 2. Oracle（按 command 匹配优先，避免漏掉 user!=oracle 的 ora_*）
    if ORACLE_RE.match(cmd) or (user == 'oracle' and cmd.startswith('oracle')):
        return 'oracle'

    # 3. Grid
    if user == 'grid' or GRID_RE.match(cmd):
        return 'grid'

    # 4. 用户脚本
    base = _cmd_basename(cmd)
    if base in USER_SCRIPT_BASENAMES:
        return 'user_script'

    # 5. 人类用户（不在系统用户列表里）
    if user and user not in SYSTEM_USERS and not user.startswith('rpc') \
            and not user.startswith('dbus') and not user.startswith('systemd-'):
        return 'user'

    # 6. 默认系统守护
    return 'system_daemon'


# ─── 11. WCHAN 分析（进程等待的内核函数）────────────────

# WCHAN 分类（man ps / 内核源码）
# 参考：/sys/kernel/debug/tracing/available_events 中的 wait 事件
#  - io:    io_schedule, blk_mq_get_tag, blk_queue_enter, get_request, ...
#  - lock:  futex, mutex_lock, rwsem_*, queue_read_lock, ...
#  - net:   do_epoll_wait, sock_recvmsg, sock_sendmsg, sk_wait, ...
#  - timer: hrtime, schedule_timeout, msleep, sys_pause, ...
#  - other: 其它（pipe_wait, inotify_read, kthread_parkme, ...）

import re as _re

WCHAN_PATTERNS: list[tuple[str, _re.Pattern]] = [
    # 注：ps 把 wchan 截到 8 字符，所以这里用短前缀匹配
    ('io', _re.compile(
        r'^(io_sched|blk_mq|blk_queu|get_req|request|blkdev_iss|congestion|'
        r'rpc_.*_sle|nfs_.*_wait|nfs_wait_b)',
        _re.I,
    )),
    ('lock', _re.compile(
        r'^(futex|mutex|rwsem|down_.*|spin|lock_|queued|'
        r'rcu_.*|call_rcu|task_rcu|__mutex|__rwsem)',
        _re.I,
    )),
    ('net', _re.compile(
        r'^(do_epo|sock_re|sock_se|sk_wa|sk_sle|inet_?c|tcp_.*|skb_wai|'
        r'afs_.*|nfs_.*_sle|rpc_.*wai|rpc_wait)',
        _re.I,
    )),
    ('timer', _re.compile(
        r'^(hrtime|schedul|msleep|usleep|sys_paus|do_usle|nanosle)',
        _re.I,
    )),
]
WCHAN_CATEGORIES: tuple[str, ...] = ('running', 'io', 'lock', 'net', 'timer', 'other')


def _wchan_category(wchan: str) -> str:
    """将 wchan 字符串分类。空 wchan 视为 running（R 状态或未等待）。"""
    if not wchan or wchan == '-':
        return 'running'
    for cat, pat in WCHAN_PATTERNS:
        if pat.match(wchan):
            return cat
    return 'other'


def _build_wchan_analysis(cycles: list[dict]) -> dict[str, Any]:
    """WCHAN 分析：每个 cycle 的 R/IO/Lock/Net/Timer/Other 数量 + Top WCHAN + 卡住进程。

    返回:
      - by_cycle:    [{timestamp, running, io, lock, net, timer, other}]
      - category_total: 各类别全周期累加
      - category_max:   各类别峰值
      - top_wchans:   [{wchan, category, count}] TOP 30
      - stuck_pids:   [{pid, user, command, wchan, category, cycles,
                        first_seen, last_seen}] 持续在异常 wchan 的进程
    """
    by_cycle: list[dict] = []
    category_total: dict[str, int] = {c: 0 for c in WCHAN_CATEGORIES}
    # 全周期 wchan 计数（用于 Top 排行）
    wchan_counts: dict[str, int] = {}
    # 跟踪每个 PID 的 wchan 历史（用于检测"卡住"的进程）
    # pid -> {wchan, count_in_this_wchan, first_seen, last_seen, user, command}
    pid_wchan: dict[int, dict] = {}

    for cyc in cycles:
        ts = cyc.get('timestamp', '')
        procs = cyc.get('processes', [])
        cats = {c: 0 for c in WCHAN_CATEGORIES}
        for p in procs:
            state = (p.get('s', '') or '').strip().upper()
            wchan = (p.get('wchan', '') or '').strip()
            # R 状态视为 running（不在等待）
            if state[:1] == 'R' or not wchan or wchan == '-':
                cats['running'] += 1
                continue
            cat = _wchan_category(wchan)
            cats[cat] += 1
            category_total[cat] += 1
            wchan_counts[wchan] = wchan_counts.get(wchan, 0) + 1

            pid = p.get('pid', 0)
            if pid:
                if pid not in pid_wchan:
                    pid_wchan[pid] = {
                        'wchan': wchan,
                        'count': 0,
                        'first_seen': ts,
                        'last_seen': ts,
                        'user': p.get('user', ''),
                        'command': p.get('command', ''),
                    }
                rec = pid_wchan[pid]
                if rec['wchan'] == wchan:
                    rec['count'] += 1
                else:
                    # PID 切换了 wchan，重置计数
                    rec['wchan'] = wchan
                    rec['count'] = 1
                    rec['first_seen'] = ts
                if ts > rec['last_seen']:
                    rec['last_seen'] = ts
        by_cycle.append({'timestamp': ts, **cats})

    # 各类别峰值
    category_max = {c: max((row.get(c, 0) for row in by_cycle), default=0) for c in WCHAN_CATEGORIES}

    # Top wchans
    top_wchans = sorted(wchan_counts.items(), key=lambda kv: -kv[1])[:30]
    top_wchans_fmt = [
        {'wchan': w, 'category': _wchan_category(w), 'count': c}
        for w, c in top_wchans
    ]

    # 卡住进程：在 io / lock 类别里、连续 ≥ 5 个 cycle 卡在同一个 wchan
    stuck_pids = []
    for pid, rec in pid_wchan.items():
        cat = _wchan_category(rec['wchan'])
        if cat not in ('io', 'lock'):
            continue
        if rec['count'] < 5:
            continue
        stuck_pids.append({
            'pid': pid,
            'user': rec['user'],
            'command': rec['command'],
            'wchan': rec['wchan'],
            'category': cat,
            'cycles': rec['count'],
            'first_seen': rec['first_seen'],
            'last_seen': rec['last_seen'],
        })
    stuck_pids.sort(key=lambda x: -x['cycles'])
    stuck_pids = stuck_pids[:50]

    return {
        'by_cycle': by_cycle,
        'category_total': category_total,
        'category_max': category_max,
        'top_wchans': top_wchans_fmt,
        'stuck_pids': stuck_pids,
        'category_order': list(WCHAN_CATEGORIES),
        'category_legend': {
            'running': '运行中（R 状态）',
            'io': 'IO 等待（io_schedule / blk_mq_*）',
            'lock': '锁等待（futex / mutex / rwsem）',
            'net': '网络等待（epoll / sock_*）',
            'timer': '定时器（hrtime / msleep）',
            'other': '其它（pipe / inotify / kthread）',
        },
    }


# ─── 12. TOP entries 补全（cpu_top / mem_top 加 STATE / WCHAN / RSS）───────────

def _enrich_top_entries(cycles: list[dict], top_entries: list[dict]) -> list[dict]:
    """为 cpu_top / mem_top 每条 entry 补全缺失的字段（RSS / STATE / WCHAN）。

    对每个 (command, user, pid) 元组，从所有 cycle 中查找：
      - 主导 state（出现次数最多）
      - 主导 wchan（出现次数最多，非 '-' 时填入）
      - RSS 最大值
      - 首次/最后出现时间（取自 cycles 的真实时间戳）
    """
    if not top_entries:
        return top_entries

    # 第一次扫描：建立 (command, user, pid) → 聚合数据的映射
    proc_data: dict[tuple[str, str, int], dict] = {}
    for cyc in cycles:
        ts = cyc.get('timestamp', '')
        for p in cyc.get('processes', []):
            cmd = p.get('command', '').strip()
            user = p.get('user', '').strip()
            pid = p.get('pid', 0)
            key = (cmd, user, pid)
            if key not in proc_data:
                proc_data[key] = {
                    'state_counts': {},
                    'wchan_counts': {},
                    'rss_max': 0,
                    'first_seen': ts,
                    'last_seen': ts,
                }
            d = proc_data[key]
            state = (p.get('s', '') or 'S').strip().upper()[:1] or 'S'
            d['state_counts'][state] = d['state_counts'].get(state, 0) + 1
            wchan = (p.get('wchan', '') or '').strip()
            if wchan and wchan != '-':
                d['wchan_counts'][wchan] = d['wchan_counts'].get(wchan, 0) + 1
            rss = p.get('rss', 0) or 0
            if rss > d['rss_max']:
                d['rss_max'] = rss
            if ts and ts < d['first_seen']:
                d['first_seen'] = ts
            if ts and ts > d['last_seen']:
                d['last_seen'] = ts

    # 第二次：补全 entry
    enriched: list[dict] = []
    for e in top_entries:
        key = (e.get('command', '').strip(), e.get('user', '').strip(), e.get('pid', 0))
        d = proc_data.get(key, {})
        # 主导 state
        state_counts = d.get('state_counts', {})
        if state_counts:
            dominant_state = max(state_counts.items(), key=lambda kv: kv[1])[0]
        else:
            dominant_state = 'S'
        # 主导 wchan（只在采样期内真的等待过才填）
        wchan_counts = d.get('wchan_counts', {})
        if wchan_counts:
            dominant_wchan = max(wchan_counts.items(), key=lambda kv: kv[1])[0]
        else:
            dominant_wchan = ''
        enriched.append({
            **e,
            'rss_max_kb': d.get('rss_max', 0),
            'state': dominant_state,
            'wchan': dominant_wchan,
            'first_seen': d.get('first_seen', e.get('first_seen', '')),
            'last_seen': d.get('last_seen', e.get('last_seen', '')),
        })
    return enriched
