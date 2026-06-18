"""
OSW-View FastAPI 后端入口。

各工具（iostat / 未来 ps/top/netstat...）的 endpoint 注册在此。
跨工具共享代码（上传/清理/扫描）见 backend/common.py。
工具专属代码见 backend/parser/<tool>/。
"""

import hashlib
import json as _json
import os
import time
import asyncio
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .common import (
    KNOWN_TOOLS,
    UPLOAD_DIR,
    UPLOAD_RETENTION_DAYS,
    cleanup_expired_files,
    cleanup_tool_dir,
    ensure_upload_dir,
    scan_supported_files,
    scan_tool_dir,
)
from .parser.iostat import IostatVersionRegistry
from .parser.iostat.exceptions import UnknownIostatFormat
from .parser.ps import PsVersionRegistry
from .parser.ps.exceptions import UnknownPsFormat
from .parser.top import TopVersionRegistry
from .parser.top.exceptions import UnknownTopFormat
from .parser.netstat import NetstatVersionRegistry
from .parser.netstat.exceptions import UnknownNetstatFormat
from .cache import json_cache as cache

from .parser.ps.analyzer import analyze_cycles as _analyze_cycles_impl
from .parser.top.analyzer import analyze_cycles as _analyze_top_cycles_impl
from .parser.netstat.analyzer import analyze_cycles as _analyze_netstat_cycles_impl


# ─── 轻量 summary 缓存 ─────────────────────────────────────────────
# 用于 ps 工具的 /api/parse/summary 端点：避免每次读 520MB cycles JSON
# key = 源文件路径（hash 算文件路径），value = summary dict
SUMMARY_CACHE_DIR = Path(__file__).resolve().parent / 'cache_data' / 'summary'


def _summary_cache_path(fpath: str) -> Path:
    SUMMARY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.md5(fpath.encode()).hexdigest()[:8]
    return SUMMARY_CACHE_DIR / f'{h}_{Path(fpath).name}.summary.json'


def get_cached_summary(fpath: str) -> dict | None:
    sp = _summary_cache_path(fpath)
    if not sp.exists():
        return None
    try:
        with open(sp, 'r', encoding='utf-8') as f:
            return _json.load(f)
    except (OSError, ValueError):
        return None


def save_cached_summary(fpath: str, summary: dict) -> None:
    sp = _summary_cache_path(fpath)
    with open(sp, 'w', encoding='utf-8') as f:
        _json.dump(summary, f, ensure_ascii=False, indent=2)


# ─── summary in-flight 锁（防并发聚合内存爆）────────────────────────
# 当多个请求同时算同一个文件的 summary 时，第二个 await 第一个的结果，
# 避免每个请求都遍历 150 万进程（1.5GB 内存 × N）。
# 单 worker uvicorn 下足够（跨进程需要文件锁/Redis，未支持）。
_inflight_summary: dict[str, asyncio.Future] = {}


# ─── ps analyze 缓存 ──────────────────────────────────────────
# 用于 /api/ps/analyze 端点（Oracle/RAC 故障排查专用分析）
# 独立于 summary 缓存，文件名后缀 .analyze.json
ANALYZE_CACHE_DIR = SUMMARY_CACHE_DIR  # 复用同一个目录


def _analyze_cache_path(fpath: str) -> Path:
    ANALYZE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.md5(fpath.encode()).hexdigest()[:8]
    return ANALYZE_CACHE_DIR / f'{h}_{Path(fpath).name}.analyze.json'


def get_cached_analyze(fpath: str) -> dict | None:
    p = _analyze_cache_path(fpath)
    if not p.exists():
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return _json.load(f)
    except (OSError, ValueError):
        return None


def save_cached_analyze(fpath: str, analysis: dict) -> None:
    p = _analyze_cache_path(fpath)
    with open(p, 'w', encoding='utf-8') as f:
        _json.dump(analysis, f, ensure_ascii=False, indent=2)


_inflight_analyze: dict[str, asyncio.Future] = {}


# ─── ps analyze response 模型 ──────────────────────────────────
# 完全描述 /api/ps/analyze 的响应结构（前端 TypeScript 类型一一对应）


class PsOverview(BaseModel):
    """总体统计：总数 + 5 分类计数 + 按 user 分布"""
    total: int
    oracle: int
    grid: int
    kernel: int
    user: int
    system_daemon: int
    user_script: int  # 单独跟踪
    by_user: list[dict]  # [{user, process_count}]


class PsTrends(BaseModel):
    """每个 cycle 一行的时序数据"""
    timestamps: list[str]
    total: list[int]
    oracle: list[int]
    grid: list[int]
    kernel: list[int]
    user: list[int]
    system_daemon: list[int]
    user_script: list[int]
    px: list[int]
    job: list[int]


class PsCpuTopEntry(BaseModel):
    command: str
    user: str
    pid: int
    cpu_pct_max: float
    cpu_pct_avg: float
    cycles_seen: int
    first_seen: str
    last_seen: str
    # 补全字段（来自 _enrich_top_entries）
    rss_max_kb: int = 0
    state: str = 'S'   # 主导状态
    wchan: str = ''    # 主导 wchan（采样期内等待过的内核函数）


class PsMemTopEntry(BaseModel):
    command: str
    user: str
    pid: int
    rss_max_kb: int
    rss_avg_kb: int
    vsz_max_kb: int
    cycles_seen: int
    first_seen: str
    last_seen: str
    # 补全字段
    cpu_pct_max: float = 0.0
    cpu_pct_avg: float = 0.0
    state: str = 'S'
    wchan: str = ''


class PsOracleAnalysis(BaseModel):
    background_counts: dict  # {kind: max_concurrent}
    background_by_cycle: list[dict]  # [{timestamp, pmon, lgwr, ...}]
    px_peak: int
    job_peak: int
    distinct_pids: dict  # {kind: pid_count}


class PsGridAnalysis(BaseModel):
    kind_counts: dict
    kind_by_cycle: list[dict]
    distinct_pids: dict
    restart_count: dict


class PsSystemAnalysis(BaseModel):
    kind_avg: dict
    kind_peak: dict
    kind_cycles: dict
    cycle_count: int


class PsUserScriptRun(BaseModel):
    pid: int
    first_seen: str
    last_seen: str
    max_cpu: float
    max_rss_kb: int
    command_sample: str


class PsUserScript(BaseModel):
    name: str
    run_count: int
    first_seen: str
    last_seen: str
    max_cpu: float
    max_rss_kb: int
    runs: list[PsUserScriptRun]


class PsStateZombiePid(BaseModel):
    pid: int
    user: str
    command: str
    first_seen: str
    last_seen: str
    cycles_z: int


class PsStateLongDPid(BaseModel):
    pid: int
    user: str
    command: str
    first_seen: str
    last_seen: str
    cycles_d: int


class PsStateAnalysis(BaseModel):
    """进程状态（R/S/D/Z/T/I/X）分析"""
    by_cycle: list[dict]  # [{timestamp, R, S, D, Z, T, I, X}]
    total_by_state: dict  # {R: x, S: y, ...}
    current: dict  # 最后一个 cycle 的状态计数
    max_z: int
    max_d: int
    max_r: int
    zombie_pids: list[PsStateZombiePid]
    long_d_pids: list[PsStateLongDPid]
    state_order: list[str]
    state_legend: dict


class PsWchanTopEntry(BaseModel):
    wchan: str
    category: str
    count: int


class PsWchanStuckPid(BaseModel):
    pid: int
    user: str
    command: str
    wchan: str
    category: str
    cycles: int
    first_seen: str
    last_seen: str


class PsWchanAnalysis(BaseModel):
    """WCHAN 分析（进程等待的内核函数）"""
    by_cycle: list[dict]  # [{timestamp, running, io, lock, net, timer, other}]
    category_total: dict
    category_max: dict
    top_wchans: list[PsWchanTopEntry]
    stuck_pids: list[PsWchanStuckPid]
    category_order: list[str]
    category_legend: dict


class PsUserTrendEntry(BaseModel):
    """单个用户的进程数时序摘要"""
    user: str
    total: int
    avg: float
    max: int


class PsUserTrends(BaseModel):
    """按用户的进程数时序数据（每用户一张图）"""
    users: list[PsUserTrendEntry]
    by_cycle: list[dict]  # [{timestamp, user1: count, user2: count, ...}]
    top_n: int


class PsLifecyclePid(BaseModel):
    pid: int
    first_seen: str
    last_seen: str


class PsLifecycleEntry(BaseModel):
    name: str
    category: str  # oracle / grid / system / script
    first_seen: str
    last_seen: str
    pid_count: int
    duration_seconds: float
    cycles_seen: int
    frequency_pct: float
    pids: list[PsLifecyclePid]


class PsAnalysisResponse(BaseModel):
    """ps 工具专用深度分析（Oracle/RAC 故障排查）"""
    cycle_count: int
    matched_versions: dict[str, list[str]]
    time_range: dict  # {start, end}
    overview: PsOverview
    trends: PsTrends
    cpu_top: list[PsCpuTopEntry]
    mem_top: list[PsMemTopEntry]
    oracle: PsOracleAnalysis
    grid: PsGridAnalysis
    system: PsSystemAnalysis
    user_scripts: list[PsUserScript]
    lifecycle: list[PsLifecycleEntry]
    state: PsStateAnalysis
    wchan: PsWchanAnalysis
    user_trends: PsUserTrends


app = FastAPI(title='OSW-View API')

PORT = 8001

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# iostat 版本注册表（启动时加载所有 versions/*/ 下的 parser）
IOSTAT_REGISTRY = IostatVersionRegistry()

# ps 版本注册表
PS_REGISTRY = PsVersionRegistry()

# top 版本注册表
TOP_REGISTRY = TopVersionRegistry()

# netstat 版本注册表
NETSTAT_REGISTRY = NetstatVersionRegistry()


# 工具注册表：parser_type → (registry, exception_class)
TOOL_REGISTRY: dict[str, tuple] = {
    'iostat': (IOSTAT_REGISTRY, UnknownIostatFormat),
    'ps': (PS_REGISTRY, UnknownPsFormat),
    'top': (TOP_REGISTRY, UnknownTopFormat),
    'netstat': (NETSTAT_REGISTRY, UnknownNetstatFormat),
}


# ─── Request/Response Models ──────────────────────────────────────────


class ScanRequest(BaseModel):
    path: str = ''  # 空字符串 + tool → 扫描默认的工具子目录（oswupdownload_file/<tool>/）
    tool: str = ''  # 工具名（iostat / ps / top ...）；path 为空时必须填


class ScanResponse(BaseModel):
    files: list[str]  # 相对路径列表
    scanned_dir: str  # 实际扫描的目录（前端展示用）
    cleaned_count: int = 0  # 本次清理掉的过期文件数
    tool: str = ''  # 本次扫描的工具子目录（如果有）


class ParseRequest(BaseModel):
    dir_path: str
    files: list[str]
    parser_type: str = 'iostat'  # iostat / ps（未来加 top / mpstat 等）
    max_cycles: int = 50  # 响应中每个文件最多返回多少个 cycle（超过则截断，标记 truncated）


class ParseResponse(BaseModel):
    cycles_count: int
    devices: list[str]
    metrics: list[str]
    cpu_metrics: list[str]
    data: dict  # 完整解析结果 JSON（按 max_cycles 截断）
    matched_versions: dict[str, list[str]] = {}  # version_id -> [basenames]
    truncated: bool = False  # 是否有文件被截断（cycle 数超过 max_cycles）
    max_cycles: int = 50  # 实际应用的截断阈值


class PsUserSummary(BaseModel):
    user: str
    cycle_count: int  # 出现过的 cycle 数（应该 = total cycles）
    process_count_avg: float  # 平均进程数
    process_count_max: int  # 单 cycle 最大进程数
    cpu_pct_avg: float  # 平均 %CPU（跨所有 cycle 的所有进程）
    cpu_pct_max: float  # 进程级 %CPU 最大值
    mem_pct_avg: float  # 平均 %MEM
    mem_pct_max: float
    rss_total_kb_avg: float  # 平均总 RSS（KB）


class PsCommandSummary(BaseModel):
    command: str
    occurrence_count: int  # 跨所有 cycle 出现的次数（一次 cycle 出现 1 次计 1）
    cycle_count: int  # 出现该 command 的 cycle 数
    cpu_pct_avg: float
    mem_pct_avg: float
    rss_avg_kb: float


class PsSummaryResponse(BaseModel):
    cycle_count: int
    total_processes: int  # 所有 cycle 的进程总数
    by_user: list[PsUserSummary]
    by_command: list[PsCommandSummary]  # Top 50 高 CPU 命令
    matched_versions: dict[str, list[str]] = {}


# ─── API Endpoints ───────────────────────────────────────────────────


@app.get('/')
def root():
    return {'message': 'OSW-View API', 'version': '0.1.0'}


@app.post('/api/scan', response_model=ScanResponse)
def scan_directory(req: ScanRequest):
    """
    扫描指定目录，返回所有 .dat 和 .dat.gz 文件列表。

    - path 非空 → 直接扫 path（任意工具通用，可指向磁盘上任意目录）
    - path 为空 + tool 非空 → 扫 oswupdownload_file/<tool>/（如 oswupdownload_file/iostat/）
    - path + tool 都为空 → 400
    - 每次调用都会顺手清理相关目录里 mtime 超过 UPLOAD_RETENTION_DAYS 的文件
    """
    if not req.path.strip() and not req.tool.strip():
        raise HTTPException(
            status_code=400,
            detail='path 和 tool 必须填一个：path 直接扫指定目录；tool 扫 oswupdownload_file/<tool>/',
        )

    cleaned = 0
    used_tool = ''

    if req.path.strip():
        # 用户指定了绝对/相对路径
        target = req.path.strip()
        if not os.path.isdir(target):
            raise HTTPException(status_code=400, detail=f'目录不存在: {target}')
        files = scan_supported_files(target)
    else:
        # 扫工具子目录
        tool = req.tool.strip()
        if tool not in KNOWN_TOOLS:
            raise HTTPException(
                status_code=400,
                detail=f'未知工具: {tool!r}，已知工具: {list(KNOWN_TOOLS)}',
            )
        used_tool = tool
        ensure_upload_dir(tool)
        cleaned = cleanup_tool_dir(tool, UPLOAD_RETENTION_DAYS)
        target = str(ensure_upload_dir(tool))
        files = scan_tool_dir(tool)

    return ScanResponse(
        files=files,
        scanned_dir=target,
        cleaned_count=cleaned,
        tool=used_tool,
    )


@app.post('/api/upload')
async def upload_files(
    files: list[UploadFile] = File(...),
    tool: str = Form(...),
):
    """
    接受 multipart 上传多个文件，存到 oswupdownload_file/<tool>/。

    - tool 必填（form field），指定存到哪个工具子目录
    - 重名时附加 8 位 hash 后缀
    - 上传时顺手清理该工具子目录里 mtime 超过 UPLOAD_RETENTION_DAYS 的文件
    """
    import hashlib as _hashlib

    if tool not in KNOWN_TOOLS:
        raise HTTPException(
            status_code=400,
            detail=f'未知工具: {tool!r}，已知工具: {list(KNOWN_TOOLS)}',
        )
    if not files:
        raise HTTPException(status_code=400, detail='未提供文件')

    target_dir = ensure_upload_dir(tool)
    cleanup_tool_dir(tool, UPLOAD_RETENTION_DAYS)

    uploaded: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []

    for f in files:
        try:
            name = Path(f.filename or '').name
            if not name:
                failed.append({'filename': '', 'reason': 'empty_filename'})
                continue
            # 后缀白名单
            if not (name.endswith('.dat') or name.endswith('.dat.gz')):
                failed.append({'filename': name, 'reason': 'unsupported_extension（仅支持 .dat / .dat.gz）'})
                continue

            # 处理重名：保留原 basename + 8 位 hash
            target = target_dir / name
            if target.exists():
                stem = target.stem  # 'xxx.dat' or 'xxx'
                suffix = ''.join(target.suffixes)  # '.dat.gz' or '.dat'
                h = _hashlib.md5((name + os.urandom(4).hex()).encode()).hexdigest()[:8]
                target = target_dir / f'{stem}-{h}{suffix}'

            content = await f.read()
            target.write_bytes(content)
            uploaded.append({'original': name, 'saved_as': target.name, 'path': str(target)})
        except Exception as e:
            failed.append({'filename': f.filename or '', 'reason': str(e)})

    return {
        'uploaded_count': len(uploaded),
        'failed_count': len(failed),
        'uploaded': uploaded,
        'failed': failed,
    }


@app.post('/api/parse', response_model=ParseResponse)
def parse_files(req: ParseRequest):
    """
    解析选中的文件。
    先检查缓存，未命中则解析并写入缓存。

    parser_type 决定走哪个工具的注册表（iostat / ps / 未来 top 等）。
    """
    if req.parser_type not in TOOL_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f'未知解析器: {req.parser_type}，已知: {list(TOOL_REGISTRY.keys())}',
        )
    registry, exc_class = TOOL_REGISTRY[req.parser_type]

    all_cycles = []
    matched_versions: dict[str, list[str]] = {}
    any_truncated = False

    def detect_or_raise_422(fpath: str) -> str:
        try:
            return registry.detect(fpath)
        except exc_class as e:
            raise HTTPException(
                status_code=422,
                detail={
                    'error': 'unknown_format',
                    'banner': getattr(e, 'banner', None),
                    'header_columns': getattr(e, 'header_columns', None)
                        or getattr(e, 'ps_header', None),
                    'pending_path': e.pending_path,
                },
            )

    for fname in req.files:
        fpath = os.path.join(req.dir_path, os.path.basename(fname))
        # 尝试从缓存读取
        cached = cache.get_cached(fpath)
        if cached is not None and cached.get('parser_type') == req.parser_type:
            all_cycles.extend(cached.get('cycles', []))
            ver = cached.get('version')
            if not ver:
                try:
                    ver = detect_or_raise_422(fpath)
                    cached['version'] = ver
                    cache.save_cache(fpath, cached)
                except HTTPException:
                    raise
            matched_versions.setdefault(ver, []).append(os.path.basename(fname))
            continue

        # 未命中缓存：先 detect 拿 version，再 parse
        ver = detect_or_raise_422(fpath)
        try:
            result = registry.versions[ver]().parse_file(fpath)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f'解析失败 {fname}: {str(e)}')

        # iostat 解析结果是 cycles 列表（每个 cycle 含 cpu/devices）
        # ps 解析结果也是 cycles 列表（每个 cycle 含 processes）
        # 都用 __dict__ 序列化（已验证 iostat 可行）
        cycles_data = [c.__dict__ for c in result.cycles]
        cache.save_cache(fpath, {
            'cycles': cycles_data,
            'version': ver,
            'parser_type': req.parser_type,
        })
        matched_versions.setdefault(ver, []).append(os.path.basename(fname))
        all_cycles.extend(cycles_data)

    # 设备列表和指标（iostat 风格；ps 暂返回空）
    devices_set: set[str] = set()
    metrics_set: set[str] = set()
    cpu_metrics_set: set[str] = set()

    for cyc in all_cycles:
        for dev in cyc.get('devices', []):
            devices_set.add(dev.get('device', ''))
        if cyc.get('cpu'):
            cpu_metrics_set.update(cyc['cpu'].keys())
        if cyc.get('devices') and len(cyc['devices']) > 0:
            metrics_set.update(k for k in cyc['devices'][0].keys() if k != 'device')

    # 按 max_cycles 截断（缓存里仍存全部，响应只返回前 N 个）
    max_cycles = max(1, req.max_cycles)
    total_cycles = len(all_cycles)
    if total_cycles > max_cycles:
        any_truncated = True
        return_cycles = all_cycles[:max_cycles]
    else:
        return_cycles = all_cycles

    return ParseResponse(
        cycles_count=total_cycles,
        devices=sorted(devices_set),
        metrics=sorted(metrics_set),
        cpu_metrics=sorted(cpu_metrics_set),
        data={'cycles': return_cycles},
        matched_versions=matched_versions,
        truncated=any_truncated,
        max_cycles=max_cycles,
    )


@app.post('/api/cache/clear')
def clear_cache(req: ScanRequest | None = None):
    """
    清除缓存。指定 path 时清除该文件缓存，否则清除全部。
    """
    if req is None:
        cache.clear_cache()
    else:
        cache.clear_cache(req.path)
    return {'message': '缓存已清除'}


# ─── 工具版本管理 endpoints ──────────────────────────────────────────


@app.get('/api/iostat/versions')
def list_iostat_versions():
    """列出所有已注册的 iostat 格式版本（来自 versions/*/manifest.json）"""
    return {'versions': IOSTAT_REGISTRY.list_versions()}


@app.get('/api/ps/versions')
def list_ps_versions():
    """列出所有已注册的 ps 格式版本（来自 versions/*/manifest.json）"""
    return {'versions': PS_REGISTRY.list_versions()}


# ─── ps 汇总 endpoint ────────────────────────────────────────────────


def _compute_ps_summary_sync(req: ParseRequest) -> PsSummaryResponse:
    """
    ps 工具专用：跨所有 cycle 算汇总统计（同步版，会遍历 150 万进程 ~14s）。

    返回：
      - by_user：按 USER 聚合（平均进程数 / 平均 CPU / 平均内存 / 总 RSS）
      - by_command：Top 50 高 CPU 命令（按出现频次 + 平均 CPU 排序）
      - cycle_count / total_processes

    不返回完整 cycles 列表（响应体小，几 KB 即可）。
    """
    if req.parser_type != 'ps':
        raise HTTPException(
            status_code=400,
            detail=f'/api/parse/summary 仅支持 parser_type="ps"，收到: {req.parser_type!r}',
        )
    if len(req.files) != 1:
        raise HTTPException(
            status_code=400,
            detail=f'/api/parse/summary 目前只支持单文件（收到 {len(req.files)} 个）',
        )
    registry, exc_class = TOOL_REGISTRY[req.parser_type]

    # 复用缓存：所有 cycle 都从 cache 拿
    all_cycles: list[dict] = []
    matched_versions: dict[str, list[str]] = {}

    def detect_or_raise_422(fpath: str) -> str:
        try:
            return registry.detect(fpath)
        except exc_class as e:
            raise HTTPException(
                status_code=422,
                detail={
                    'error': 'unknown_format',
                    'banner': getattr(e, 'banner', None),
                    'header_columns': getattr(e, 'header_columns', None)
                        or getattr(e, 'ps_header', None),
                    'pending_path': e.pending_path,
                },
            )

    for fname in req.files:
        fpath = os.path.join(req.dir_path, os.path.basename(fname))
        cached = cache.get_cached(fpath)
        if cached is not None and cached.get('parser_type') == req.parser_type:
            all_cycles.extend(cached.get('cycles', []))
            ver = cached.get('version')
            if not ver:
                try:
                    ver = detect_or_raise_422(fpath)
                    cached['version'] = ver
                    cache.save_cache(fpath, cached)
                except HTTPException:
                    raise
            matched_versions.setdefault(ver, []).append(os.path.basename(fname))
            continue

        # cache miss：detect + parse + 写缓存
        ver = detect_or_raise_422(fpath)
        try:
            result = registry.versions[ver]().parse_file(fpath)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f'解析失败 {fname}: {str(e)}')

        cycles_data = [c.__dict__ for c in result.cycles]
        cache.save_cache(fpath, {
            'cycles': cycles_data,
            'version': ver,
            'parser_type': req.parser_type,
        })
        matched_versions.setdefault(ver, []).append(os.path.basename(fname))
        all_cycles.extend(cycles_data)

    # ─── 聚合统计（首次/缓存失效时跑）─────────────────────
    cycle_count = len(all_cycles)
    total_processes = sum(len(c.get('processes', [])) for c in all_cycles)

    # 按 USER 聚合
    user_stats: dict[str, dict] = {}  # user -> {count_sum, count_max, cpu_sum, cpu_max, mem_sum, mem_max, rss_sum, cycle_count}
    for cyc in all_cycles:
        procs = cyc.get('processes', [])
        if not procs:
            continue
        # 该 cycle 各 USER 的统计
        cycle_user_count: dict[str, int] = {}
        for p in procs:
            u = p.get('user', '')
            if u not in user_stats:
                user_stats[u] = {
                    'count_sum': 0, 'count_max': 0,
                    'cpu_sum': 0.0, 'cpu_max': 0.0,
                    'mem_sum': 0.0, 'mem_max': 0.0,
                    'rss_sum': 0,
                    'cycle_count': 0,
                }
            s = user_stats[u]
            s['count_sum'] += 1
            s['cpu_sum'] += p.get('cpu_pct', 0.0)
            s['cpu_max'] = max(s['cpu_max'], p.get('cpu_pct', 0.0))
            s['mem_sum'] += p.get('mem_pct', 0.0)
            s['mem_max'] = max(s['mem_max'], p.get('mem_pct', 0.0))
            s['rss_sum'] += p.get('rss', 0)
            cycle_user_count[u] = cycle_user_count.get(u, 0) + 1
        # 每个出现过的 user 的 count_max = 该 cycle 出现次数的最大值
        for u, cnt in cycle_user_count.items():
            user_stats[u]['count_max'] = max(user_stats[u]['count_max'], cnt)
            user_stats[u]['cycle_count'] += 1

    by_user = []
    for u, s in sorted(user_stats.items(), key=lambda kv: -kv[1]['count_sum']):
        cc = s['cycle_count']
        pc_total = s['count_sum']
        by_user.append(PsUserSummary(
            user=u,
            cycle_count=cc,
            process_count_avg=round(pc_total / cc, 1) if cc else 0,
            process_count_max=s['count_max'],
            cpu_pct_avg=round(s['cpu_sum'] / pc_total, 2) if pc_total else 0,
            cpu_pct_max=round(s['cpu_max'], 2),
            mem_pct_avg=round(s['mem_sum'] / pc_total, 2) if pc_total else 0,
            mem_pct_max=round(s['mem_max'], 2),
            rss_total_kb_avg=round(s['rss_sum'] / cc, 0) if cc else 0,
        ))

    # 按 COMMAND 聚合（top 50，按 occurrence_count 排序）
    cmd_stats: dict[str, dict] = {}  # command -> {count, cycle_set, cpu_sum, mem_sum, rss_sum}
    for cyc in all_cycles:
        for p in cyc.get('processes', []):
            cmd = p.get('command', '').strip()
            if not cmd:
                continue
            if cmd not in cmd_stats:
                cmd_stats[cmd] = {
                    'count': 0, 'cycle_set': set(),
                    'cpu_sum': 0.0, 'mem_sum': 0.0, 'rss_sum': 0,
                }
            cs = cmd_stats[cmd]
            cs['count'] += 1
            cs['cycle_set'].add(cyc.get('timestamp', ''))
            cs['cpu_sum'] += p.get('cpu_pct', 0.0)
            cs['mem_sum'] += p.get('mem_pct', 0.0)
            cs['rss_sum'] += p.get('rss', 0)

    by_command = []
    # 先按 occurrence_count 排，再按 cpu 平均排
    sorted_cmds = sorted(
        cmd_stats.items(),
        key=lambda kv: (-kv[1]['count'], -kv[1]['cpu_sum'] / kv[1]['count']),
    )
    for cmd, cs in sorted_cmds[:50]:
        cnt = cs['count']
        by_command.append(PsCommandSummary(
            command=cmd,
            occurrence_count=cnt,
            cycle_count=len(cs['cycle_set']),
            cpu_pct_avg=round(cs['cpu_sum'] / cnt, 2) if cnt else 0,
            mem_pct_avg=round(cs['mem_sum'] / cnt, 2) if cnt else 0,
            rss_avg_kb=round(cs['rss_sum'] / cnt, 0) if cnt else 0,
        ))

    return PsSummaryResponse(
        cycle_count=cycle_count,
        total_processes=total_processes,
        by_user=by_user,
        by_command=by_command,
        matched_versions=matched_versions,
    )


@app.post('/api/parse/summary', response_model=PsSummaryResponse)
async def ps_summary(req: ParseRequest):
    """
    ps 工具专用 endpoint（async + in-flight 锁）：
      1) 命中独立 summary cache（毫秒级）→ 直接返回
      2) 命中 in-flight future → await 别人正在算的结果（防并发聚合 OOM）
      3) 真的算：扔到线程池跑 14s 阻塞工作（不卡 asyncio 事件循环）
    """
    if req.parser_type != 'ps':
        raise HTTPException(
            status_code=400,
            detail=f'/api/parse/summary 仅支持 parser_type="ps"，收到: {req.parser_type!r}',
        )
    if len(req.files) != 1:
        raise HTTPException(
            status_code=400,
            detail=f'/api/parse/summary 目前只支持单文件（收到 {len(req.files)} 个）',
        )
    fpath = os.path.join(req.dir_path, os.path.basename(req.files[0]))

    # 1) 独立 cache 命中（毫秒级）
    cached = get_cached_summary(fpath)
    if cached is not None:
        return PsSummaryResponse(**cached)

    # 2) in-flight 命中：await 已经在算的 future
    if fpath in _inflight_summary:
        existing = _inflight_summary[fpath]
        result_dict = await existing
        return PsSummaryResponse(**result_dict)

    # 3) 真算：扔到线程池跑（不卡事件循环）
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    _inflight_summary[fpath] = future
    try:
        # run_in_executor(None, ...) 用默认 ThreadPoolExecutor
        result_obj = await loop.run_in_executor(None, _compute_ps_summary_sync, req)
        result_dict = result_obj.dict()  # PsSummaryResponse -> dict
        # 写独立 cache，下次毫秒级
        try:
            save_cached_summary(fpath, result_dict)
        except Exception:
            pass
        future.set_result(result_dict)
        return PsSummaryResponse(**result_dict)
    finally:
        # 清理 in-flight 锁（无论成功失败）
        _inflight_summary.pop(fpath, None)


# ─── ps analyze endpoint ──────────────────────────────────────────
# Oracle/RAC 故障排查专用：分类、趋势、TOP N、生命周期
# 复用 cycles 缓存（parse 已做），独立缓存 analyze 结果
# 单文件、~20s 计算，缓存命中后毫秒级


def _compute_ps_analyze_sync(req: ParseRequest) -> PsAnalysisResponse:
    """ps 工具专用深度分析（同步版，会遍历全部 cycles ~20s）。

    返回结构见 PsAnalysisResponse 的字段文档。
    """
    if req.parser_type != 'ps':
        raise HTTPException(
            status_code=400,
            detail=f'/api/ps/analyze 仅支持 parser_type="ps"，收到: {req.parser_type!r}',
        )
    if len(req.files) != 1:
        raise HTTPException(
            status_code=400,
            detail=f'/api/ps/analyze 目前只支持单文件（收到 {len(req.files)} 个）',
        )
    registry, exc_class = TOOL_REGISTRY[req.parser_type]

    def detect_or_raise_422(fpath: str) -> str:
        try:
            return registry.detect(fpath)
        except exc_class as e:
            raise HTTPException(
                status_code=422,
                detail={
                    'error': 'unknown_format',
                    'banner': getattr(e, 'banner', None),
                    'header_columns': getattr(e, 'header_columns', None)
                        or getattr(e, 'ps_header', None),
                    'pending_path': e.pending_path,
                },
            )

    fname = req.files[0]
    fpath = os.path.join(req.dir_path, os.path.basename(fname))

    # 复用 cycles 缓存（注意：ps 大文件的 cache 只存了 version/parser_type，不存 cycles，
    # 此时需要 fall through 到 parse 重新生成 cycles）
    cached = cache.get_cached(fpath)
    if cached is not None and cached.get('parser_type') == req.parser_type and cached.get('cycles'):
        # 缓存命中：cycles 已经在 dict 列表里（JSON 反序列化结果）
        cycles_for_analyze = cached['cycles']
        ver = cached.get('version') or detect_or_raise_422(fpath)
        matched_versions = {ver: [os.path.basename(fname)]}
    else:
        # cache miss / 只存了 version：parse + 写缓存
        ver = cached.get('version') if cached else None
        if not ver:
            ver = detect_or_raise_422(fpath)
        try:
            result = registry.versions[ver]().parse_file(fpath)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f'解析失败 {fname}: {str(e)}')

        # 写缓存：ps 大文件（>200MB）只存 version/parser_type，避免 OOM
        # 这里的 version 信息已经够 detect 用，下次请求会重新 parse（~17s）
        cache._save_version_only(fpath, {
            'cycles': [],  # dummy 给 _save_version_only 用
            'version': ver,
            'parser_type': req.parser_type,
        })
        # 给 analyzer 用 PsCycle dataclass 对象（内存紧凑，~700MB 而非 1.5GB+）
        cycles_for_analyze = result.cycles
        matched_versions = {ver: [os.path.basename(fname)]}

    # 跑分析器（单次遍历）
    analysis = _analyze_cycles_impl(cycles_for_analyze)
    analysis['cycle_count'] = len(cycles_for_analyze)
    analysis['matched_versions'] = matched_versions

    return PsAnalysisResponse(**analysis)


@app.post('/api/ps/analyze', response_model=PsAnalysisResponse)
async def ps_analyze(req: ParseRequest):
    """ps 工具专用深度分析（Oracle/RAC 故障排查）。

    与旧的 /api/parse/summary 区别：
      - summary：通用聚合（按 USER / 按 COMMAND 两张表）
      - analyze：Oracle 故障排查专用（分类、趋势、TOP N、生命周期）

    异步 + 独立缓存 + in-flight 锁（避免并发聚合 OOM）。
    """
    if req.parser_type != 'ps':
        raise HTTPException(
            status_code=400,
            detail=f'/api/ps/analyze 仅支持 parser_type="ps"，收到: {req.parser_type!r}',
        )
    if len(req.files) != 1:
        raise HTTPException(
            status_code=400,
            detail=f'/api/ps/analyze 目前只支持单文件（收到 {len(req.files)} 个）',
        )
    fpath = os.path.join(req.dir_path, os.path.basename(req.files[0]))

    # 1) 独立 cache 命中
    cached = get_cached_analyze(fpath)
    if cached is not None:
        return PsAnalysisResponse(**cached)

    # 2) in-flight 命中
    if fpath in _inflight_analyze:
        existing = _inflight_analyze[fpath]
        result_dict = await existing
        return PsAnalysisResponse(**result_dict)

    # 3) 真算
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    _inflight_analyze[fpath] = future
    try:
        result_obj = await loop.run_in_executor(None, _compute_ps_analyze_sync, req)
        result_dict = result_obj.dict()
        try:
            save_cached_analyze(fpath, result_dict)
        except Exception:
            pass
        future.set_result(result_dict)
        return PsAnalysisResponse(**result_dict)
    finally:
        _inflight_analyze.pop(fpath, None)


# ─── top analyze endpoint ──────────────────────────────────
# OSW top 日志专用：系统摘要（load/cpu/mem/swap） + 进程分析（TOP N/分类/状态）
# 复用 cycles 缓存，独立缓存 analyze 结果


class TopOverview(BaseModel):
    """总体概览"""
    cycle_count: int
    total_procs: int
    load_1m_max: float
    cpu_us_max: float
    cpu_wa_max: float
    total: int
    oracle: int
    grid: int
    kernel: int
    user: int
    system_daemon: int
    user_script: int
    by_user: list[dict]


class TopSystemTrends(BaseModel):
    """系统摘要时序（load/cpu/mem/swap 等 25 维）"""
    timestamps: list[str]
    load_1m: list[float]
    load_5m: list[float]
    load_15m: list[float]
    tasks_total: list[int]
    tasks_running: list[int]
    tasks_sleeping: list[int]
    tasks_stopped: list[int]
    tasks_zombie: list[int]
    cpu_us: list[float]
    cpu_sy: list[float]
    cpu_ni: list[float]
    cpu_id: list[float]
    cpu_wa: list[float]
    cpu_hi: list[float]
    cpu_si: list[float]
    cpu_st: list[float]
    mem_total: list[float]
    mem_used: list[float]
    mem_free: list[float]
    mem_buff: list[float]
    mem_pct: list[float]
    swap_total: list[float]
    swap_used: list[float]
    avail_mem: list[float]


class TopCpuTopEntry(BaseModel):
    command: str
    user: str
    pid: int
    cpu_pct_max: float
    cpu_pct_avg: float
    cycles_seen: int
    first_seen: str
    last_seen: str
    res_kb_max: int = 0
    state: str = 'S'
    mem_pct_max: float = 0.0
    mem_pct_avg: float = 0.0
    # 出现在该指标（cpu_pct）每个 cycle TOP 5 之前的次数
    # 反映"程序持续在 CPU 占用前列"的稳定性，比峰值更能说明长期资源占用
    top5_count: int = 0


class TopMemTopEntry(BaseModel):
    command: str
    user: str
    pid: int
    res_kb_max: int
    res_kb_avg: int
    virt_kb_max: int
    cycles_seen: int
    cpu_pct_max: float = 0.0
    cpu_pct_avg: float = 0.0
    mem_pct_max: float = 0.0
    mem_pct_avg: float = 0.0
    first_seen: str
    last_seen: str
    state: str = 'S'
    # 出现在该指标（mem_pct）每个 cycle TOP 5 之前的次数
    top5_count: int = 0


class TopProcessCategories(BaseModel):
    """进程分类时序"""
    timestamps: list[str]
    total: list[int]
    oracle: list[int]
    grid: list[int]
    kernel: list[int]
    user: list[int]
    system_daemon: list[int]
    user_script: list[int]


class TopUserDistributionEntry(BaseModel):
    user: str
    total: int
    avg: float
    max: int


class TopUserDistribution(BaseModel):
    """按用户的进程数时序数据"""
    users: list[TopUserDistributionEntry]
    by_cycle: list[dict]
    top_n: int


class TopStateLongDPid(BaseModel):
    pid: int
    user: str
    command: str
    first_seen: str
    last_seen: str
    cycles_d: int


class TopStateZombiePid(BaseModel):
    pid: int
    user: str
    command: str
    first_seen: str
    last_seen: str
    cycles_z: int


class TopStateTrends(BaseModel):
    """进程状态（R/S/D/Z/T/I）时序"""
    by_cycle: list[dict]
    total_by_state: dict
    current: dict
    max_d: int
    max_z: int
    max_r: int
    long_d_pids: list[TopStateLongDPid]
    zombie_pids: list[TopStateZombiePid]
    state_order: list[str]
    state_legend: dict


class TopProgramCpuTimelineProgram(BaseModel):
    """Top 进程 CPU 时序中的单个程序"""
    command: str
    total_cpu: float
    cycles_seen: int
    avg_cpu: float


class TopProgramCpuTimeline(BaseModel):
    """按 command 聚合的 CPU% 时序（top 20，跨用户/PID 求和）

    给定程序（如 'gzip'）在每个 cycle 的 CPU% = 该 cycle 中所有同名进程
    的 CPU% 之和（4 个 gzip × 100% = 400%，代表占用了 4 个核）。
    """
    programs: list[TopProgramCpuTimelineProgram]
    by_cycle: list[dict]
    top_n: int


class TopAnalysisResponse(BaseModel):
    """top 工具专用深度分析（系统摘要 + 进程分析）"""
    cycle_count: int
    matched_versions: dict[str, list[str]]
    time_range: dict
    overview: TopOverview
    system_trends: TopSystemTrends
    cpu_top: list[TopCpuTopEntry]
    mem_top: list[TopMemTopEntry]
    process_categories: TopProcessCategories
    user_distribution: TopUserDistribution
    state_trends: TopStateTrends
    program_cpu_timeline: TopProgramCpuTimeline


class TopInfoResponse(BaseModel):
    """top 时间点驱动视图专用：仅返回时间滑块 + landscape 需要的字段。

    比 /api/top/analyze 小一个数量级（~5KB vs ~500KB），
    因为省略了 cpu_top/mem_top/overview/state_trends/process_categories/
    user_distribution/program_cpu_timeline 这些新视图不用的数据。
    """
    cycle_count: int
    matched_versions: dict[str, list[str]]
    time_range: dict
    # 完整的 timestamps 列表（用于时间滑块）和 load 1m（用于 landscape）
    timestamps: list[str]
    load_1m: list[float]
    # 1 分钟的 system_trends（其他指标省略，新视图的上下文卡用 snapshot 自带的 summary）


# ─── top analyze 独立缓存（与 ps 共用目录，独立 key）─────────
TOP_ANALYZE_CACHE_DIR = SUMMARY_CACHE_DIR  # 复用


def _top_analyze_cache_path(fpath: str) -> Path:
    TOP_ANALYZE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.md5(fpath.encode()).hexdigest()[:8]
    return TOP_ANALYZE_CACHE_DIR / f'{h}_{Path(fpath).name}.top_analyze.json'


def get_cached_top_analyze(fpath: str) -> dict | None:
    p = _top_analyze_cache_path(fpath)
    if not p.exists():
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return _json.load(f)
    except (OSError, ValueError):
        return None


def save_cached_top_analyze(fpath: str, analysis: dict) -> None:
    p = _top_analyze_cache_path(fpath)
    with open(p, 'w', encoding='utf-8') as f:
        _json.dump(analysis, f, ensure_ascii=False, indent=2)


_inflight_top_analyze: dict[str, asyncio.Future] = {}


def _compute_top_analyze_sync(req: ParseRequest) -> TopAnalysisResponse:
    """top 工具专用深度分析（同步版）。"""
    if req.parser_type != 'top':
        raise HTTPException(
            status_code=400,
            detail=f'/api/top/analyze 仅支持 parser_type="top"，收到: {req.parser_type!r}',
        )
    if len(req.files) != 1:
        raise HTTPException(
            status_code=400,
            detail=f'/api/top/analyze 目前只支持单文件（收到 {len(req.files)} 个）',
        )
    registry, exc_class = TOOL_REGISTRY[req.parser_type]

    def detect_or_raise_422(fpath: str) -> str:
        try:
            return registry.detect(fpath)
        except exc_class as e:
            raise HTTPException(
                status_code=422,
                detail={
                    'error': 'unknown_format',
                    'banner': getattr(e, 'banner', None),
                    'header_columns': getattr(e, 'top_header', None)
                        or getattr(e, 'ps_header', None)
                        or getattr(e, 'header_columns', None),
                    'pending_path': e.pending_path,
                },
            )

    fname = req.files[0]
    fpath = os.path.join(req.dir_path, os.path.basename(fname))

    # 复用 cycles 缓存
    cached = cache.get_cached(fpath)
    if cached is not None and cached.get('parser_type') == req.parser_type and cached.get('cycles'):
        # 缓存命中：cycles 已经是 dict 列表（summary 是嵌套 dict）
        # 还原成 TopCycle dataclass 让 analyzer 用
        from .parser.top import TopCycle, TopSummary
        cycles_for_analyze = []
        for c in cached['cycles']:
            s = c.get('summary') or {}
            summary = TopSummary(**s) if isinstance(s, dict) else s
            procs = c.get('processes', [])
            cycles_for_analyze.append(TopCycle(
                timestamp=c.get('timestamp', ''),
                summary=summary,
                processes=procs,
            ))
        ver = cached.get('version') or detect_or_raise_422(fpath)
        matched_versions = {ver: [os.path.basename(fname)]}
    else:
        # cache miss：parse + 写缓存
        ver = cached.get('version') if cached else None
        if not ver:
            ver = detect_or_raise_422(fpath)
        try:
            result = registry.versions[ver]().parse_file(fpath)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f'解析失败 {fname}: {str(e)}')

        cache._save_version_only(fpath, {
            'cycles': [],
            'version': ver,
            'parser_type': req.parser_type,
        })
        cycles_for_analyze = result.cycles
        matched_versions = {ver: [os.path.basename(fname)]}

    # 跑分析器
    analysis = _analyze_top_cycles_impl(cycles_for_analyze)
    analysis['cycle_count'] = len(cycles_for_analyze)
    analysis['matched_versions'] = matched_versions

    return TopAnalysisResponse(**analysis)


@app.post('/api/top/analyze', response_model=TopAnalysisResponse)
async def top_analyze(req: ParseRequest):
    """top 工具专用深度分析（系统摘要 + 进程分析）。

    异步 + 独立缓存 + in-flight 锁（避免并发聚合 OOM）。
    """
    if req.parser_type != 'top':
        raise HTTPException(
            status_code=400,
            detail=f'/api/top/analyze 仅支持 parser_type="top"，收到: {req.parser_type!r}',
        )
    if len(req.files) != 1:
        raise HTTPException(
            status_code=400,
            detail=f'/api/top/analyze 目前只支持单文件（收到 {len(req.files)} 个）',
        )
    fpath = os.path.join(req.dir_path, os.path.basename(req.files[0]))

    # 1) 独立 cache 命中
    cached = get_cached_top_analyze(fpath)
    if cached is not None:
        return TopAnalysisResponse(**cached)

    # 2) in-flight 命中
    if fpath in _inflight_top_analyze:
        existing = _inflight_top_analyze[fpath]
        result_dict = await existing
        return TopAnalysisResponse(**result_dict)

    # 3) 真算
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    _inflight_top_analyze[fpath] = future
    try:
        result_obj = await loop.run_in_executor(None, _compute_top_analyze_sync, req)
        result_dict = result_obj.dict()
        try:
            save_cached_top_analyze(fpath, result_dict)
        except Exception:
            pass
        future.set_result(result_dict)
        return TopAnalysisResponse(**result_dict)
    finally:
        _inflight_top_analyze.pop(fpath, None)


@app.get('/api/top/versions')
def list_top_versions():
    """列出所有已注册的 top 格式版本（来自 versions/*/manifest.json）"""
    return {'versions': TOP_REGISTRY.list_versions()}


@app.post('/api/top/info', response_model=TopInfoResponse)
def top_info(req: ParseRequest):
    """top 时间点驱动视图专用：仅返回时间滑块 + landscape 需要的字段。

    与 /api/top/analyze 的区别：
      - 省略 cpu_top/mem_top/overview/state_trends/process_categories/
        user_distribution/program_cpu_timeline（新视图不用的数据）
      - 响应 ~5KB（vs analyze 的 ~500KB）
      - 仍复用 json_cache 解析缓存
    """
    cycles, matched_versions = _load_top_cycles(req)
    if not cycles:
        raise HTTPException(status_code=400, detail='文件无 cycle 数据')

    # 汇总：timestamps + load_1m（landscape 只需要这一个指标）
    timestamps = [c.timestamp for c in cycles]
    load_1m: list[float] = []
    for c in cycles:
        s = c.summary
        load_1m.append(float(getattr(s, 'load_avg_1m', 0) or 0) if s else 0.0)

    time_range = {
        'start': cycles[0].timestamp,
        'end': cycles[-1].timestamp,
    }

    return TopInfoResponse(
        cycle_count=len(cycles),
        matched_versions=matched_versions,
        time_range=time_range,
        timestamps=timestamps,
        load_1m=load_1m,
    )


# ─── /api/top/top_programs 端点 ───────────────────────────
# 配套第 2 段：整个时间段的程序占用 TOP 20（按 command+user 跨所有 cycle 聚合）
# 复用 _analyze_top_cycles_impl 但只取 cpu_top + mem_top，响应 ~12KB
# （vs /api/top/analyze 的 ~500KB）


class TopProgramsRequest(BaseModel):
    dir_path: str
    files: list[str]
    parser_type: str = 'top'


class TopProgramsResponse(BaseModel):
    cpu_top: list[TopCpuTopEntry]
    mem_top: list[TopMemTopEntry]
    cycle_count: int
    matched_versions: dict[str, list[str]]


@app.post('/api/top/top_programs', response_model=TopProgramsResponse)
def top_programs(req: TopProgramsRequest):
    """第 2 段用：整个时间段的程序占用 TOP 20（按出现在 TOP 5 之前的次数排序）。

    排序逻辑：统计每个 (command, user) 在多少个 cycle 出现在
    对应指标（cpu_pct / mem_pct）前 5 名，按次数降序。
    比按峰值 max 排序更能反映"程序持续在抢资源"。
    """
    cycles, matched_versions = _load_top_cycles(req)
    if not cycles:
        raise HTTPException(status_code=400, detail='文件无 cycle 数据')

    # analyzer 接受 list of dict 或 list of dataclass；_load_top_cycles 返回 dataclass
    cycles_dicts: list[dict] = []
    for c in cycles:
        cycles_dicts.append({
            'timestamp': c.timestamp,
            'processes': [p if isinstance(p, dict) else p.__dict__ for p in c.processes],
            'summary': c.summary.__dict__ if hasattr(c.summary, '__dict__') else (c.summary or {}),
        })

    # 直接调用 top5 排序函数（不走 _analyze_top_cycles_impl 的 cpu_top/mem_top，那是按 max 排序的）
    from .parser.top.analyzer import _build_cpu_top_by_top5, _build_mem_top_by_top5
    cpu_top = _build_cpu_top_by_top5(cycles_dicts, top_n=20)
    mem_top = _build_mem_top_by_top5(cycles_dicts, top_n=20)

    return TopProgramsResponse(
        cpu_top=cpu_top,
        mem_top=mem_top,
        cycle_count=len(cycles),
        matched_versions=matched_versions,
    )


# ─── top snapshot + pid_history 端点 ───────────────────
# 配套 TopView 的"时间点驱动"探查器：
#   - /api/top/snapshot    → 取指定 cycle 的进程列表（默认按 %CPU 降序）
#   - /api/top/pid_history → 取指定 PID 在所有 cycle 的时序（含 cpu_pct/mem_pct/res_kb/state）
# 这两个端点共用 _load_top_cycles() 加载逻辑（cache 命中或重新 parse）


class TopSnapshotProcess(BaseModel):
    pid: int
    user: str
    pr: int
    ni: int
    virt_kb: int
    res_kb: int
    shr_kb: int
    s: str
    cpu_pct: float
    mem_pct: float
    time_str: str
    command: str


class TopSnapshotRequest(BaseModel):
    dir_path: str
    files: list[str]
    parser_type: str = 'top'
    cycle_index: int = 0
    sort_by: str = 'cpu_pct'  # cpu_pct | mem_pct | res_kb | virt_kb | pid
    sort_desc: bool = True


class TopSnapshotResponse(BaseModel):
    cycle_index: int
    total_cycles: int
    timestamp: str
    summary: dict  # TopSummary 字段（load/cpu/mem/swap/tasks）
    processes: list[TopSnapshotProcess]
    matched_versions: dict[str, list[str]]


def _load_top_cycles(req: ParseRequest) -> tuple[list, dict]:
    """从 cache 加载 cycles，或重新 parse。返回 (cycles, matched_versions)。

    失败抛 HTTPException(422 unknown_format | 500 parse_failed)。
    """
    if req.parser_type != 'top':
        raise HTTPException(
            status_code=400,
            detail=f'仅支持 parser_type="top"，收到: {req.parser_type!r}',
        )
    if len(req.files) != 1:
        raise HTTPException(
            status_code=400,
            detail=f'仅支持单文件（收到 {len(req.files)} 个）',
        )
    fpath = os.path.join(req.dir_path, os.path.basename(req.files[0]))
    registry, exc_class = TOOL_REGISTRY[req.parser_type]

    def _detect_or_raise_422() -> str:
        try:
            return registry.detect(fpath)
        except exc_class as e:
            raise HTTPException(
                status_code=422,
                detail={
                    'error': 'unknown_format',
                    'banner': getattr(e, 'banner', None),
                    'header_columns': getattr(e, 'top_header', None),
                    'pending_path': e.pending_path,
                },
            )

    cached = cache.get_cached(fpath)
    if cached is not None and cached.get('parser_type') == req.parser_type and cached.get('cycles'):
        # 缓存命中：cycles 已在 dict 列表里（含 summary 嵌套）
        from .parser.top import TopCycle, TopSummary
        cycles = []
        for c in cached['cycles']:
            s = c.get('summary') or {}
            summary = TopSummary(**s) if isinstance(s, dict) else s
            cycles.append(TopCycle(
                timestamp=c.get('timestamp', ''),
                summary=summary,
                processes=c.get('processes', []),
            ))
        ver = cached.get('version') or _detect_or_raise_422()
        return cycles, {ver: [os.path.basename(fpath)]}

    # cache miss 或只存了 version：parse + 写**全** cycles 缓存
    # top 数据量适中（~7MB < 200MB 限制），存全量比 version-only 更利于
    # snapshot/pid_history 复用（避免每次重 parse ~500ms）
    ver = cached.get('version') if cached else None
    if not ver:
        ver = _detect_or_raise_422()
    try:
        result = registry.versions[ver]().parse_file(fpath)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'解析失败 {req.files[0]}: {str(e)}')
    # 序列化 cycles 为 dict（含 summary 嵌套）再写 cache
    cycles_data = []
    for c in result.cycles:
        cycles_data.append({
            'timestamp': c.timestamp,
            'summary': c.summary.__dict__ if hasattr(c.summary, '__dict__') else (c.summary or {}),
            'processes': [p if isinstance(p, dict) else p.__dict__ for p in c.processes],
        })
    cache.save_cache(fpath, {
        'cycles': cycles_data,
        'version': ver,
        'parser_type': req.parser_type,
    })
    return result.cycles, {ver: [os.path.basename(req.files[0])]}


@app.post('/api/top/snapshot', response_model=TopSnapshotResponse)
def top_snapshot(req: TopSnapshotRequest):
    """取指定 cycle 的进程列表（按指定字段排序，默认 %CPU 降序）。"""
    parse_req = ParseRequest(
        dir_path=req.dir_path,
        files=req.files,
        parser_type=req.parser_type,
    )
    cycles, matched_versions = _load_top_cycles(parse_req)
    if not cycles:
        raise HTTPException(status_code=400, detail='文件无 cycle 数据')

    # cycle_index 越界则 clamp
    idx = max(0, min(req.cycle_index, len(cycles) - 1))
    cyc = cycles[idx]
    summary_dict = cyc.summary.__dict__ if hasattr(cyc.summary, '__dict__') else (cyc.summary or {})

    # 按指定字段排序
    procs = [p if isinstance(p, dict) else p.__dict__ for p in cyc.processes]
    sort_key = req.sort_by
    if sort_key in ('cpu_pct', 'mem_pct'):
        procs.sort(key=lambda p: float(p.get(sort_key) or 0.0), reverse=req.sort_desc)
    elif sort_key in ('res_kb', 'virt_kb', 'shr_kb', 'pr', 'ni', 'pid'):
        procs.sort(key=lambda p: int(p.get(sort_key) or 0), reverse=req.sort_desc)
    elif sort_key == 'time_str':
        procs.sort(key=lambda p: str(p.get(sort_key) or ''), reverse=req.sort_desc)
    elif sort_key in ('user', 'command', 's'):
        procs.sort(key=lambda p: str(p.get(sort_key) or ''), reverse=req.sort_desc)
    else:
        procs.sort(key=lambda p: float(p.get('cpu_pct') or 0.0), reverse=True)

    return TopSnapshotResponse(
        cycle_index=idx,
        total_cycles=len(cycles),
        timestamp=cyc.timestamp,
        summary=summary_dict,
        processes=procs,
        matched_versions=matched_versions,
    )


class TopPidHistoryPoint(BaseModel):
    cycle_index: int
    timestamp: str
    cpu_pct: float
    mem_pct: float
    res_kb: int
    virt_kb: int
    shr_kb: int
    s: str
    pr: int
    ni: int
    time_str: str
    user: str
    command: str


class TopPidHistoryRequest(BaseModel):
    dir_path: str
    files: list[str]
    parser_type: str = 'top'
    pid: int
    # 可选：聚焦到该 cycle 前后 ±N 个 cycles 范围内（默认全周期）
    focus_cycle_index: int | None = None
    focus_window: int = 0  # 0 = 全周期；>0 = ±N cycles


class TopPidHistoryResponse(BaseModel):
    pid: int
    command: str
    user: str
    first_seen_cycle: int
    last_seen_cycle: int
    first_seen_ts: str
    last_seen_ts: str
    cycles_seen: int
    total_cycles: int
    history: list[TopPidHistoryPoint]
    matched_versions: dict[str, list[str]]


# ─── /api/top/landscape 端点 ───────────────────────────
# 配套第 1 段：多指标 chip + 聚合方式 + PID 搜索 → 一张大图
# - pid=null 时：跨所有进程聚合（avg/max/sum）
# - pid=N    时：只取该 PID 在每个 cycle 的值（agg 仍适用，但效果等同单进程）
# - metrics：选哪些列（cpu_pct/mem_pct/virt_kb/res_kb/shr_kb/pr/ni/load_1m）
# - agg     ：avg | max | sum
# - load_1m 是系统级指标（来自 summary），不受 pid 过滤影响

class TopLandscapeRequest(BaseModel):
    dir_path: str
    files: list[str]
    parser_type: str = 'top'
    pid: int | None = None
    metrics: list[str] = ['cpu_pct', 'mem_pct']
    agg: str = 'avg'  # avg | max | sum


class TopLandscapeSeries(BaseModel):
    name: str
    data: list  # [[ts, val], ...]


class TopLandscapeResponse(BaseModel):
    pid: int | None
    agg: str
    metrics: list[str]
    timestamps: list[str]
    series: list[TopLandscapeSeries]
    cycles_seen: int  # pid 出现过的 cycle 数（无 pid 过滤时 = 总 cycle 数）
    matched_versions: dict[str, list[str]]


# 合法指标 → 显示标签
_LANDSCAPE_METRIC_LABELS = {
    'cpu_pct': '%CPU',
    'mem_pct': '%MEM',
    'virt_kb': 'VIRT',
    'res_kb': 'RES',
    'shr_kb': 'SHR',
    'pr': 'PR',
    'ni': 'NI',
    'load_1m': 'load 1m',
}
_LANDSCAPE_VALID_METRICS = set(_LANDSCAPE_METRIC_LABELS.keys())


@app.post('/api/top/landscape', response_model=TopLandscapeResponse)
def top_landscape(req: TopLandscapeRequest):
    """第 1 段 landscape 图：多指标 + 聚合 + 可选 PID 过滤。"""
    parse_req = ParseRequest(
        dir_path=req.dir_path,
        files=req.files,
        parser_type=req.parser_type,
    )
    cycles, matched_versions = _load_top_cycles(parse_req)
    if not cycles:
        raise HTTPException(status_code=400, detail='文件无 cycle 数据')

    target_pid = req.pid
    agg = req.agg
    if agg not in ('avg', 'max', 'sum'):
        agg = 'avg'

    metrics = [m for m in req.metrics if m in _LANDSCAPE_VALID_METRICS]
    if not metrics:
        raise HTTPException(
            status_code=400,
            detail=f'未指定有效指标，合法: {sorted(_LANDSCAPE_VALID_METRICS)}',
        )

    series_values: dict[str, list[float]] = {m: [] for m in metrics}
    timestamps: list[str] = []
    cycles_seen = 0

    for cyc in cycles:
        timestamps.append(cyc.timestamp)
        procs = [p if isinstance(p, dict) else p.__dict__ for p in cyc.processes]

        # PID 过滤
        if target_pid is not None:
            procs = [p for p in procs if int(p.get('pid') or 0) == target_pid]
            if procs:
                cycles_seen += 1

        for metric in metrics:
            # 特殊：load_1m 来自 summary
            if metric == 'load_1m':
                s = cyc.summary
                val = float(getattr(s, 'load_avg_1m', 0) or 0) if s else 0.0
                series_values[metric].append(round(val, 2))
                continue

            if not procs:
                series_values[metric].append(0.0)
                continue

            values: list[float] = []
            for p in procs:
                v = p.get(metric)
                if v is None:
                    continue
                if metric in ('pr', 'ni'):
                    try:
                        values.append(float(int(v)))
                    except (ValueError, TypeError):
                        pass
                else:
                    try:
                        values.append(float(v))
                    except (ValueError, TypeError):
                        pass

            if not values:
                series_values[metric].append(0.0)
                continue

            if agg == 'max':
                val = max(values)
            elif agg == 'sum':
                val = sum(values)
            else:
                val = sum(values) / len(values)
            series_values[metric].append(round(val, 2))

    series: list[dict] = []
    for metric in metrics:
        label = _LANDSCAPE_METRIC_LABELS[metric]
        if target_pid is not None:
            name = f'PID {target_pid} · {label}'
        else:
            name = f'{label} ({agg})'
        series.append({
            'name': name,
            'data': [[timestamps[i], series_values[metric][i]] for i in range(len(timestamps))],
        })

    return TopLandscapeResponse(
        pid=target_pid,
        agg=agg,
        metrics=metrics,
        timestamps=timestamps,
        series=series,
        cycles_seen=cycles_seen if target_pid is not None else len(cycles),
        matched_versions=matched_versions,
    )


@app.post('/api/top/pid_history', response_model=TopPidHistoryResponse)
def top_pid_history(req: TopPidHistoryRequest):
    """取指定 PID 在所有 cycle 的时序（按 cycle 顺序）。

    注意：PID 可能被复用。本端点按 pid 匹配所有同名 PID 的进程，
    但附加 user + command 的一致性检查（同 user + 同 command 才算同一个进程）。
    """
    parse_req = ParseRequest(
        dir_path=req.dir_path,
        files=req.files,
        parser_type=req.parser_type,
    )
    cycles, matched_versions = _load_top_cycles(parse_req)
    if not cycles:
        raise HTTPException(status_code=400, detail='文件无 cycle 数据')

    target_pid = req.pid
    history: list[TopPidHistoryPoint] = []
    first_user: str = ''
    first_cmd: str = ''

    for i, cyc in enumerate(cycles):
        for p in cyc.processes:
            p_dict = p if isinstance(p, dict) else p.__dict__
            if int(p_dict.get('pid') or 0) != target_pid:
                continue
            user = str(p_dict.get('user', '')).strip()
            cmd = str(p_dict.get('command', '')).strip()
            if not first_user:
                first_user = user
                first_cmd = cmd
            # 一致性：user + command 保持不变（应对 PID 复用）
            # 这里不强求严格一致，仅采集所有命中
            history.append(TopPidHistoryPoint(
                cycle_index=i,
                timestamp=cyc.timestamp,
                cpu_pct=float(p_dict.get('cpu_pct') or 0.0),
                mem_pct=float(p_dict.get('mem_pct') or 0.0),
                res_kb=int(p_dict.get('res_kb') or 0),
                virt_kb=int(p_dict.get('virt_kb') or 0),
                shr_kb=int(p_dict.get('shr_kb') or 0),
                s=str(p_dict.get('s', '')).strip(),
                pr=int(p_dict.get('pr') or 0),
                ni=int(p_dict.get('ni') or 0),
                time_str=str(p_dict.get('time_str', '')).strip(),
                user=user,
                command=cmd,
            ))
            break  # 每个 cycle 最多取 1 条（同 PID 多行不常见）

    # 可选 focus 窗口
    if req.focus_window > 0 and req.focus_cycle_index is not None and history:
        lo = max(0, req.focus_cycle_index - req.focus_window)
        hi = min(len(cycles) - 1, req.focus_cycle_index + req.focus_window)
        history = [h for h in history if lo <= h.cycle_index <= hi]

    if history:
        first_seen = history[0]
        last_seen = history[-1]
    else:
        first_seen = last_seen = None  # type: ignore

    return TopPidHistoryResponse(
        pid=target_pid,
        command=first_cmd,
        user=first_user,
        first_seen_cycle=first_seen.cycle_index if first_seen else -1,
        last_seen_cycle=last_seen.cycle_index if last_seen else -1,
        first_seen_ts=first_seen.timestamp if first_seen else '',
        last_seen_ts=last_seen.timestamp if last_seen else '',
        cycles_seen=len(history),
        total_cycles=len(cycles),
        history=history,
        matched_versions=matched_versions,
    )


# ═══════════════════════════════════════════════════════════════════
# netstat 端点（oswnetstat 工具）
# ═══════════════════════════════════════════════════════════════════
# 设计参照 top：
#   - /api/netstat/info        → 轻量入口（timestamps 列表 + 上下文）
#   - /api/netstat/snapshot    → 单 cycle 接口 + kernel_counters
#   - /api/netstat/landscape   → 多指标多接口时序（每个接口一张图）
#   - /api/netstat/top_interfaces → TOP N 接口（按累计流量）
#   - /api/netstat/versions    → 已注册版本列表


# ─── netstat analyze 独立缓存 ───────────────────────────

NETSTAT_ANALYZE_CACHE_DIR = SUMMARY_CACHE_DIR  # 复用


def _netstat_analyze_cache_path(fpath: str) -> Path:
    NETSTAT_ANALYZE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.md5(fpath.encode()).hexdigest()[:8]
    return NETSTAT_ANALYZE_CACHE_DIR / f'{h}_{Path(fpath).name}.netstat_analyze.json'


def get_cached_netstat_analyze(fpath: str) -> dict | None:
    p = _netstat_analyze_cache_path(fpath)
    if not p.exists():
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return _json.load(f)
    except (OSError, ValueError):
        return None


def save_cached_netstat_analyze(fpath: str, analysis: dict) -> None:
    p = _netstat_analyze_cache_path(fpath)
    with open(p, 'w', encoding='utf-8') as f:
        _json.dump(analysis, f, ensure_ascii=False, indent=2)


_inflight_netstat_analyze: dict[str, asyncio.Future] = {}


# ─── loader ──────────────────────────────────────────────


def _load_netstat_cycles(req: ParseRequest) -> tuple[list, dict]:
    """从 cache 加载 netstat cycles，或重新 parse。返回 (cycles, matched_versions)。

    失败抛 HTTPException(422 unknown_format | 500 parse_failed)。
    """
    if req.parser_type != 'netstat':
        raise HTTPException(
            status_code=400,
            detail=f'仅支持 parser_type="netstat"，收到: {req.parser_type!r}',
        )
    if len(req.files) != 1:
        raise HTTPException(
            status_code=400,
            detail=f'仅支持单文件（收到 {len(req.files)} 个）',
        )
    fpath = os.path.join(req.dir_path, os.path.basename(req.files[0]))
    registry, exc_class = TOOL_REGISTRY[req.parser_type]

    def _detect_or_raise_422() -> str:
        try:
            return registry.detect(fpath)
        except exc_class as e:
            raise HTTPException(
                status_code=422,
                detail={
                    'error': 'unknown_format',
                    'banner': getattr(e, 'banner', None),
                    'section_marker': getattr(e, 'section_marker', None),
                    'pending_path': e.pending_path,
                },
            )

    cached = cache.get_cached(fpath)
    if cached is not None and cached.get('parser_type') == req.parser_type and cached.get('cycles'):
        # 缓存命中：cycles 已在 dict 列表里（含 interfaces + kernel_counters 嵌套）
        from .parser.netstat import NetstatCycle
        cycles = []
        for c in cached['cycles']:
            cycles.append(NetstatCycle(
                timestamp=c.get('timestamp', ''),
                interfaces=c.get('interfaces', []),
                kernel_counters=c.get('kernel_counters', {}),
            ))
        ver = cached.get('version') or _detect_or_raise_422()
        return cycles, {ver: [os.path.basename(fpath)]}

    # cache miss 或只存了 version：parse + 写**全** cycles 缓存
    ver = cached.get('version') if cached else None
    if not ver:
        ver = _detect_or_raise_422()
    try:
        result = registry.versions[ver]().parse_file(fpath)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'解析失败 {req.files[0]}: {str(e)}')
    # 序列化 cycles 为 dict 再写 cache
    cycles_data = []
    for c in result.cycles:
        cycles_data.append({
            'timestamp': c.timestamp,
            'interfaces': c.interfaces,
            'kernel_counters': c.kernel_counters,
        })
    cache.save_cache(fpath, {
        'cycles': cycles_data,
        'version': ver,
        'parser_type': req.parser_type,
    })
    return result.cycles, {ver: [os.path.basename(req.files[0])]}


# ─── NetstatRates：差分/dt 算出接口速率（MB/s、pps、errors/s）────────


class NetstatRatesRequest(BaseModel):
    dir_path: str
    files: list[str]
    parser_type: str = 'netstat'


class NetstatInterfaceRates(BaseModel):
    """一个接口的差值序列（每个 cycle 一个值，cycle[0] 设为 0 因为没有前值）

    *_delta：相邻 cycle 计数器的差值（不除以时间），即每个采样窗口内真实收发的字节数。
    """
    # 字节差值（不除以 dt）— 前端只用这一个
    rx_bytes_delta: list[int] = []
    tx_bytes_delta: list[int] = []


class NetstatRatesResponse(BaseModel):
    """每个接口的速率序列 + timestamps + 元信息"""
    cycle_count: int
    timestamps: list[str]
    interface_rates: dict[str, NetstatInterfaceRates]  # {iface_name: rates}
    time_range: dict
    # 累计字节（首末 cycle 差值）— Overview "总接收/发送流量" 卡片用
    total_rx_bytes: int = 0
    total_tx_bytes: int = 0
    # 最后 cycle 的 kernel counter 快照（Overview TCP Connections / Retrans 卡片用）
    last_kernel_counters: dict[str, int] = {}
    matched_versions: dict[str, list[str]]


def _parse_iso_ts(ts: str) -> datetime | None:
    """解析 ISO timestamp（如 '2026-06-15T13:00:04'）"""
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _build_interface_rates(cycles: list) -> dict[str, NetstatInterfaceRates]:
    """对每个接口算 (cycle[i] - cycle[i-1]) 的字节差值（不除以时间）。

    counter 单调递增，差分 = 该 dt 内的字节增量。
    cycle[0] 没有前值，设为 0（前端展示时跳过第一点）。
    """
    # 收集所有出现过的接口名
    all_ifaces: set[str] = set()
    for c in cycles:
        for i in c.interfaces:
            n = i.get('name', '')
            if n:
                all_ifaces.add(n)

    result: dict[str, NetstatInterfaceRates] = {
        n: NetstatInterfaceRates() for n in all_ifaces
    }

    for iface_name in all_ifaces:
        rates = result[iface_name]
        for i, c in enumerate(cycles):
            if i == 0:
                # 第一个 cycle 没有前值，置 0
                rates.rx_bytes_delta.append(0)
                rates.tx_bytes_delta.append(0)
                continue

            cur = next((x for x in c.interfaces if x.get('name') == iface_name), None)
            prev = next((x for x in cycles[i-1].interfaces if x.get('name') == iface_name), None)
            if cur is None or prev is None:
                # 该 cycle 或前一个 cycle 无此接口
                rates.rx_bytes_delta.append(0)
                rates.tx_bytes_delta.append(0)
                continue

            # counter 单调递增；counter 跳变（重启）时 delta 可能为负，按 0 处理
            def delta_raw(cur_v: int, prev_v: int) -> int:
                return max(cur_v - prev_v, 0)

            rates.rx_bytes_delta.append(delta_raw(int(cur.get('rx_bytes', 0) or 0), int(prev.get('rx_bytes', 0) or 0)))
            rates.tx_bytes_delta.append(delta_raw(int(cur.get('tx_bytes', 0) or 0), int(prev.get('tx_bytes', 0) or 0)))

    return result


@app.post('/api/netstat/rates', response_model=NetstatRatesResponse)
def netstat_rates(req: NetstatRatesRequest):
    """计算每个接口的 RX/TX 速率（bytes/s, pps, errors/s）。

    算法：相邻 cycle 差分 / dt_sec。counter 单调递增（异常跳变按 0 处理）。
    """
    if req.parser_type != 'netstat':
        raise HTTPException(
            status_code=400,
            detail=f'仅支持 parser_type="netstat"，收到: {req.parser_type!r}',
        )
    if len(req.files) != 1:
        raise HTTPException(
            status_code=400,
            detail=f'仅支持单文件（收到 {len(req.files)} 个）',
        )

    parse_req = ParseRequest(
        dir_path=req.dir_path, files=req.files, parser_type=req.parser_type,
    )
    cycles, matched_versions = _load_netstat_cycles(parse_req)
    if not cycles:
        raise HTTPException(status_code=400, detail='文件无 cycle 数据')

    timestamps = [c.timestamp for c in cycles]
    time_range = {
        'start': timestamps[0] if timestamps else '',
        'end': timestamps[-1] if timestamps else '',
    }
    interface_rates = _build_interface_rates(cycles)

    # 累计字节 = 最后 cycle 全部接口 rx_bytes 总和（counter 单调递增，差值即整段流量）
    last_cycle = cycles[-1] if cycles else None
    total_rx_bytes = 0
    total_tx_bytes = 0
    if last_cycle:
        for i in last_cycle.interfaces:
            total_rx_bytes += int(i.get('rx_bytes', 0) or 0)
            total_tx_bytes += int(i.get('tx_bytes', 0) or 0)
    # 减去首 cycle 累计值，得到"采样期间增量"
    if len(cycles) >= 2:
        first_cycle = cycles[0]
        for i in first_cycle.interfaces:
            total_rx_bytes -= int(i.get('rx_bytes', 0) or 0)
            total_tx_bytes -= int(i.get('tx_bytes', 0) or 0)
    total_rx_bytes = max(total_rx_bytes, 0)
    total_tx_bytes = max(total_tx_bytes, 0)

    # 最后 cycle 的 kernel counter 快照
    last_kc = dict(last_cycle.kernel_counters) if last_cycle else {}

    return NetstatRatesResponse(
        cycle_count=len(cycles),
        timestamps=timestamps,
        interface_rates=interface_rates,
        time_range=time_range,
        total_rx_bytes=total_rx_bytes,
        total_tx_bytes=total_tx_bytes,
        last_kernel_counters=last_kc,
        matched_versions=matched_versions,
    )


# ─── Request/Response Models ──────────────────────────────


class NetstatSnapshotInterface(BaseModel):
    """一个网络接口的 snapshot 视图（精简字段，前端表格用）"""
    name: str
    ifindex: int = 0
    flags: str = ''
    mtu: int = 0
    state: str = ''
    master: str = ''
    link_addr: str = ''
    altname: str = ''
    rx_bytes: int = 0
    rx_packets: int = 0
    rx_errors: int = 0
    rx_dropped: int = 0
    rx_missed: int = 0
    rx_mcast: int = 0
    tx_bytes: int = 0
    tx_packets: int = 0
    tx_errors: int = 0
    tx_dropped: int = 0
    tx_carrier: int = 0
    tx_collsns: int = 0


class NetstatSnapshotRequest(BaseModel):
    dir_path: str
    files: list[str]
    parser_type: str = 'netstat'
    cycle_index: int = 0


class NetstatSnapshotResponse(BaseModel):
    cycle_index: int
    total_cycles: int
    timestamp: str
    interfaces: list[NetstatSnapshotInterface]
    kernel_counters: dict[str, int]
    matched_versions: dict[str, list[str]]


class NetstatInfoResponse(BaseModel):
    """netstat 时间点驱动视图专用：仅返回时间戳列表 + 上下文（轻量）"""
    cycle_count: int
    matched_versions: dict[str, list[str]]
    time_range: dict
    timestamps: list[str]
    interface_names: list[str]  # 最后一个 cycle 的接口列表


class NetstatKernelLandscapeRequest(BaseModel):
    """kernel counter 时序图请求。metrics 是要查看的 counter 名（如 TcpRetransSegs）。"""
    dir_path: str
    files: list[str]
    parser_type: str = 'netstat'
    metrics: list[str]  # kernel counter 名列表（如 ['TcpRetransSegs', 'TcpAttemptFails']）


class NetstatKernelLandscapeResponse(BaseModel):
    metrics: list[str]
    timestamps: list[str]
    series: list[dict]  # [{name: 'TcpRetransSegs', data: [[ts, val], ...]}, ...]
    matched_versions: dict[str, list[str]]


class NetstatLandscapeRequest(BaseModel):
    dir_path: str
    files: list[str]
    parser_type: str = 'netstat'
    interfaces: list[str]  # 要看哪些接口
    metrics: list[str] = ['rx_bytes', 'tx_bytes']


class NetstatLandscapeResponse(BaseModel):
    interfaces: list[str]
    metrics: list[str]
    timestamps: list[str]
    series: list[dict]  # [{name: 'ens1f0/rx_bytes', data: [[ts, val], ...]}, ...]
    matched_versions: dict[str, list[str]]


class NetstatTopInterfacesRequest(BaseModel):
    dir_path: str
    files: list[str]
    parser_type: str = 'netstat'


class NetstatTopInterfaceEntry(BaseModel):
    name: str
    rx_bytes: int
    tx_bytes: int
    state: str
    mtu: int


class NetstatTopInterfacesResponse(BaseModel):
    rx_bytes: list[NetstatTopInterfaceEntry]
    tx_bytes: list[NetstatTopInterfaceEntry]
    total_bytes: list[NetstatTopInterfaceEntry]
    cycle_count: int
    matched_versions: dict[str, list[str]]


# ─── /api/netstat/versions ────────────────────────────────


@app.get('/api/netstat/versions')
def list_netstat_versions():
    """列出已注册的 netstat 格式版本"""
    return {'versions': NETSTAT_REGISTRY.list_versions()}


# ─── /api/netstat/info ──────────────────────────────────


@app.post('/api/netstat/info', response_model=NetstatInfoResponse)
def netstat_info(req: ParseRequest):
    """netstat 时间点驱动视图专用：仅返回时间戳列表 + 上下文（轻量）。

    与 /api/netstat/landscape 的区别：landscape 需要遍历所有 cycles 聚合指标；
    info 只取每个 cycle 的 timestamp + 最后一个 cycle 的接口列表。
    """
    cycles, matched_versions = _load_netstat_cycles(req)
    if not cycles:
        raise HTTPException(status_code=400, detail='文件无 cycle 数据')

    timestamps = [c.timestamp for c in cycles]

    # 最后一个 cycle 的接口列表（让前端能直接展示 "网络接口"）
    last_interfaces = cycles[-1].interfaces if cycles else []
    interface_names = [i.get('name', '') for i in last_interfaces if i.get('name')]

    time_range = {
        'start': cycles[0].timestamp,
        'end': cycles[-1].timestamp,
    }

    return NetstatInfoResponse(
        cycle_count=len(cycles),
        matched_versions=matched_versions,
        time_range=time_range,
        timestamps=timestamps,
        interface_names=interface_names,
    )


# ─── /api/netstat/snapshot ──────────────────────────────


@app.post('/api/netstat/snapshot', response_model=NetstatSnapshotResponse)
def netstat_snapshot(req: NetstatSnapshotRequest):
    """取指定 cycle 的接口列表 + kernel_counters（用于时间滑块切换）。"""
    parse_req = ParseRequest(
        dir_path=req.dir_path, files=req.files, parser_type=req.parser_type,
    )
    cycles, matched_versions = _load_netstat_cycles(parse_req)
    if not cycles:
        raise HTTPException(status_code=400, detail='文件无 cycle 数据')
    if req.cycle_index < 0 or req.cycle_index >= len(cycles):
        raise HTTPException(
            status_code=400,
            detail=f'cycle_index 越界：0..{len(cycles)-1}，收到 {req.cycle_index}',
        )

    cyc = cycles[req.cycle_index]
    return NetstatSnapshotResponse(
        cycle_index=req.cycle_index,
        total_cycles=len(cycles),
        timestamp=cyc.timestamp,
        interfaces=[NetstatSnapshotInterface(**i) for i in cyc.interfaces],
        kernel_counters=dict(cyc.kernel_counters),
        matched_versions=matched_versions,
    )


# ─── /api/netstat/iface_trends ──────────────────────────


class NetstatIfaceTrendsRequest(BaseModel):
    dir_path: str
    files: list[str]
    parser_type: str = 'netstat'


class NetstatIfaceTrendsResponse(BaseModel):
    """所有 cycle × 所有接口 × 12 个计数器的累计值时序（用于"总统概览"画趋势图）。"""
    timestamps: list[str]
    interface_names: list[str]  # 所有出现过的接口名（按首次出现顺序）
    series: list[dict]  # [{name: 'ens1f0/rx_bytes', data: [[ts, val], ...]}, ...]
    matched_versions: dict[str, list[str]]


# 12 个计数器：6 RX + 6 TX（用户参考文档）
IFACE_METRICS = [
    'rx_bytes', 'rx_packets', 'rx_errors', 'rx_dropped', 'rx_missed', 'rx_mcast',
    'tx_bytes', 'tx_packets', 'tx_errors', 'tx_dropped', 'tx_carrier', 'tx_collsns',
]


@app.post('/api/netstat/iface_trends', response_model=NetstatIfaceTrendsResponse)
def netstat_iface_trends(req: NetstatIfaceTrendsRequest):
    """总统概览 tab 用：返回每接口在所有 cycle 上的累计计数器时序（不差分）。"""
    parse_req = ParseRequest(
        dir_path=req.dir_path, files=req.files, parser_type=req.parser_type,
    )
    cycles, matched_versions = _load_netstat_cycles(parse_req)
    if not cycles:
        raise HTTPException(status_code=400, detail='文件无 cycle 数据')

    timestamps = [c.timestamp for c in cycles]

    # 收集所有出现过的接口名（按首次出现顺序）
    seen: set[str] = set()
    interface_names: list[str] = []
    for c in cycles:
        for i in c.interfaces:
            n = i.get('name', '')
            if n and n not in seen:
                seen.add(n)
                interface_names.append(n)

    # 每个接口的每个指标，遍历所有 cycles 提取值
    series: list[dict] = []
    for name in interface_names:
        for metric in IFACE_METRICS:
            data: list[list] = []
            for c in cycles:
                iface = next((x for x in c.interfaces if x.get('name') == name), None)
                val = int(iface.get(metric, 0) or 0) if iface is not None else 0
                data.append([c.timestamp, val])
            series.append({'name': f'{name}/{metric}', 'data': data})

    return NetstatIfaceTrendsResponse(
        timestamps=timestamps,
        interface_names=interface_names,
        series=series,
        matched_versions=matched_versions,
    )


# ─── /api/netstat/landscape ─────────────────────────────


@app.post('/api/netstat/landscape', response_model=NetstatLandscapeResponse)
def netstat_landscape(req: NetstatLandscapeRequest):
    """多指标多接口时序图（每个接口的每个指标一张小图）。"""
    if req.parser_type != 'netstat':
        raise HTTPException(
            status_code=400,
            detail=f'仅支持 parser_type="netstat"，收到: {req.parser_type!r}',
        )
    if len(req.files) != 1:
        raise HTTPException(
            status_code=400,
            detail=f'仅支持单文件（收到 {len(req.files)} 个）',
        )
    if not req.interfaces:
        raise HTTPException(status_code=400, detail='interfaces 不能为空')
    if not req.metrics:
        raise HTTPException(status_code=400, detail='metrics 不能为空')

    parse_req = ParseRequest(
        dir_path=req.dir_path,
        files=req.files,
        parser_type=req.parser_type,
    )
    cycles, matched_versions = _load_netstat_cycles(parse_req)
    if not cycles:
        raise HTTPException(status_code=400, detail='文件无 cycle 数据')

    timestamps = [c.timestamp for c in cycles]
    # 收集所有接口的 metric 时序
    series: list[dict] = []
    for metric in req.metrics:
        for iface_name in req.interfaces:
            data: list = []
            for cyc in cycles:
                # 在该 cycle 中找这个接口
                found = next(
                    (i for i in cyc.interfaces if i.get('name') == iface_name),
                    None,
                )
                if found is not None:
                    val = int(found.get(metric, 0) or 0)
                else:
                    val = 0
                data.append([cyc.timestamp, val])
            series.append({
                'name': f'{iface_name}/{metric}',
                'data': data,
            })

    return NetstatLandscapeResponse(
        interfaces=req.interfaces,
        metrics=req.metrics,
        timestamps=timestamps,
        series=series,
        matched_versions=matched_versions,
    )


# ─── /api/netstat/kernel_landscape ─────────────────────


@app.post('/api/netstat/kernel_landscape', response_model=NetstatKernelLandscapeResponse)
def netstat_kernel_landscape(req: NetstatKernelLandscapeRequest):
    """kernel counter 时序图（如 TcpRetransSegs / TcpAttemptFails 等的时序）。"""
    if req.parser_type != 'netstat':
        raise HTTPException(
            status_code=400,
            detail=f'仅支持 parser_type="netstat"，收到: {req.parser_type!r}',
        )
    if len(req.files) != 1:
        raise HTTPException(
            status_code=400,
            detail=f'仅支持单文件（收到 {len(req.files)} 个）',
        )
    if not req.metrics:
        raise HTTPException(status_code=400, detail='metrics 不能为空')

    parse_req = ParseRequest(
        dir_path=req.dir_path,
        files=req.files,
        parser_type=req.parser_type,
    )
    cycles, matched_versions = _load_netstat_cycles(parse_req)
    if not cycles:
        raise HTTPException(status_code=400, detail='文件无 cycle 数据')

    timestamps = [c.timestamp for c in cycles]
    series: list[dict] = []
    for metric in req.metrics:
        data: list = []
        for cyc in cycles:
            val = int(cyc.kernel_counters.get(metric, 0) or 0)
            data.append([cyc.timestamp, val])
        series.append({'name': metric, 'data': data})

    return NetstatKernelLandscapeResponse(
        metrics=req.metrics,
        timestamps=timestamps,
        series=series,
        matched_versions=matched_versions,
    )


# ─── /api/netstat/top_interfaces ────────────────────────


@app.post('/api/netstat/top_interfaces', response_model=NetstatTopInterfacesResponse)
def netstat_top_interfaces(req: NetstatTopInterfacesRequest):
    """整个时间段的 TOP N 接口（按累计流量排序）。

    排序规则：按最后一个 cycle 的 rx_bytes / tx_bytes / (rx+tx) 降序。
    """
    parse_req = ParseRequest(
        dir_path=req.dir_path, files=req.files, parser_type=req.parser_type,
    )
    cycles, matched_versions = _load_netstat_cycles(parse_req)
    if not cycles:
        raise HTTPException(status_code=400, detail='文件无 cycle 数据')

    last = cycles[-1]
    stats: list[dict] = []
    for iface in last.interfaces:
        name = iface.get('name', '')
        if not name:
            continue
        stats.append({
            'name': name,
            'rx_bytes': int(iface.get('rx_bytes', 0) or 0),
            'tx_bytes': int(iface.get('tx_bytes', 0) or 0),
            'state': iface.get('state', ''),
            'mtu': int(iface.get('mtu', 0) or 0),
        })

    by_rx = sorted(stats, key=lambda x: -x['rx_bytes'])[:20]
    by_tx = sorted(stats, key=lambda x: -x['tx_bytes'])[:20]
    by_total = sorted(stats, key=lambda x: -(x['rx_bytes'] + x['tx_bytes']))[:20]

    return NetstatTopInterfacesResponse(
        rx_bytes=[NetstatTopInterfaceEntry(**s) for s in by_rx],
        tx_bytes=[NetstatTopInterfaceEntry(**s) for s in by_tx],
        total_bytes=[NetstatTopInterfaceEntry(**s) for s in by_total],
        cycle_count=len(cycles),
        matched_versions=matched_versions,
    )

