"""
iostat 版本化解析器的行为测试。
按 TDD vertical slices 推进：每个测试对应一个 slice 的行为。
"""

import os
import shutil
from pathlib import Path

import pytest


VERSIONS_DIR = Path(__file__).parent.parent / 'parser' / 'iostat' / 'versions'
SAMPLE_FIXTURES = {
    'v0001': '/root/projects/osw-view/log_source_dir/20260525_249/oswiostat/'
             + sorted(os.listdir('/root/projects/osw-view/log_source_dir/20260525_249/oswiostat/'))[0],
    'v0002': '/root/projects/osw-view/log_source_dir/20260609_cq_analyze/'
             + sorted(os.listdir('/root/projects/osw-view/log_source_dir/20260609_cq_analyze/'))[0],
}


# ─── Slice 1: v0001 端到端 ─────────────────────────────────────────────


def test_v0001_sample_parses_through_registry():
    """v0001 样本文件能被 registry 解析出 cycles 和非空 devices 列表"""
    from backend.parser.iostat import IostatVersionRegistry

    registry = IostatVersionRegistry()
    result = registry.parse(str(VERSIONS_DIR / 'v0001' / 'sample.dat.gz'))

    assert len(result.cycles) > 0, '应该至少解析出一个 cycle'
    non_empty = [c for c in result.cycles if c.devices]
    assert len(non_empty) > 0, '每个 cycle 的 devices 列表不应全空'
    # v0001 旧 OSWbb 数据有 7 个设备（dm-0/1, sda-e）
    first = non_empty[0]
    assert first.devices[0]['device'], '设备名不应为空'


# ─── Slice 2: v0002 端到端 ─────────────────────────────────────────────


def test_v0002_sample_parses_through_registry():
    """v0002 样本文件（WQWbb 新格式）能被 registry 解析出 cycles 和非空 devices"""
    from backend.parser.iostat import IostatVersionRegistry

    registry = IostatVersionRegistry()
    result = registry.parse(str(VERSIONS_DIR / 'v0002' / 'sample.dat.gz'))

    assert len(result.cycles) > 0
    non_empty = [c for c in result.cycles if c.devices]
    assert len(non_empty) > 0, 'v0002 设备的 devices 列表不应全空'
    # v0002 设备名前缀可能是 nvme/md/dm/drbd
    first_dev = non_empty[0].devices[0]['device']
    assert any(first_dev.startswith(p) for p in ('nvme', 'sd', 'dm-', 'md', 'drbd', 'vd')), \
        f'v0002 设备名前缀不在预期集合: {first_dev!r}'


# ─── 守护测试：sample 必须只包含 1 个 zzz 块 ────────────────────────


@pytest.mark.parametrize('version', ['v0001', 'v0002'])
def test_sample_contains_single_zzz_block(version):
    """sample.dat.gz 是「单次采集」样本——只允许 1 个 zzz 块

    防止后续误把完整 .dat.gz 文件复制到 versions/ 下作为 sample。
    """
    import gzip
    sample = VERSIONS_DIR / version / 'sample.dat.gz'
    with gzip.open(sample, mode='rt', encoding='utf-8', errors='replace') as f:
        text = f.read()
    zzz_lines = [l for l in text.splitlines() if l.startswith('zzz ')]
    assert len(zzz_lines) == 1, \
        f'{version}/sample.dat.gz 应只含 1 个 zzz 块（单次采集样本），实际 {len(zzz_lines)} 个'


# ─── Slice 7: fingerprint extractor 工具 ────────────────────────────


def test_extract_fingerprint_from_v0001_sample():
    """从 v0001 sample 提取 fingerprint：banner、device_header、cpu_header"""
    from backend.parser.iostat.fingerprint import extract_fingerprint

    fp = extract_fingerprint(VERSIONS_DIR / 'v0001' / 'sample.dat.gz')

    assert fp['banner'] == 'Linux OSWbb v7.3.3'
    # v0001 device header 应包含 13 个标准列
    assert fp['device_header'] is not None
    assert '%util' in fp['device_header']
    assert 'r/s' in fp['device_header']
    assert 'avgrq-sz' in fp['device_header']
    # cpu_header 应包含 6 列
    assert fp['cpu_header'] is not None
    assert set(fp['cpu_header']) == {'%user', '%nice', '%system', '%iowait', '%steal', '%idle'}


def test_extract_fingerprint_from_v0002_sample():
    """从 v0002 sample 提取 fingerprint：5 个新列应出现"""
    from backend.parser.iostat.fingerprint import extract_fingerprint

    fp = extract_fingerprint(VERSIONS_DIR / 'v0002' / 'sample.dat.gz')

    assert fp['banner'] == 'Linux WQWbb v7.3.3'
    assert fp['device_header'] is not None
    # v0002 扩展 5 列
    for col in ('%rrqm', '%wrqm', 'aqu-sz', 'rareq-sz', 'wareq-sz'):
        assert col in fp['device_header'], f'v0002 fingerprint 缺少 {col}'


def test_extract_fingerprint_handles_missing_sections():
    """对空文件 / 只有 banner 的文件，缺失 section 应返回 None"""
    import gzip
    import tempfile
    from backend.parser.iostat.fingerprint import extract_fingerprint

    with tempfile.NamedTemporaryFile(mode='wb', suffix='.dat.gz', delete=False) as f:
        with gzip.open(f, mode='wt') as gz:
            gz.write('Linux Stubbb v1.0\n')  # 只有 banner
        path = f.name

    fp = extract_fingerprint(path)
    assert fp['banner'] == 'Linux Stubbb v1.0'
    assert fp['device_header'] is None
    assert fp['cpu_header'] is None

    import os
    os.unlink(path)


# ─── Slice 9: detect 改为 fingerprint JSON 驱动 ──────────────────────


def test_detect_uses_fingerprint_json_for_v0001():
    """detect 走 fingerprint JSON（已生成 fingerprint.json）→ 仍命中 v0001"""
    from backend.parser.iostat import IostatVersionRegistry
    registry = IostatVersionRegistry()
    ver = registry.detect(str(VERSIONS_DIR / 'v0001' / 'sample.dat.gz'))
    assert ver == 'v0001'


def test_detect_uses_fingerprint_json_for_v0002():
    """detect 走 fingerprint JSON → 命中 v0002"""
    from backend.parser.iostat import IostatVersionRegistry
    registry = IostatVersionRegistry()
    ver = registry.detect(str(VERSIONS_DIR / 'v0002' / 'sample.dat.gz'))
    assert ver == 'v0002'


def test_detect_rejects_banner_impersonation():
    """banner 冒充 v0001 但 device_header 不同 → 抛 UnknownIostatFormat（不再误判 v0001）"""
    import gzip
    import tempfile
    from backend.parser.iostat import IostatVersionRegistry
    from backend.parser.iostat.exceptions import UnknownIostatFormat

    # banner 写 OSWbb（冒充 v0001），但 device_header 是新列（既不在 v0001 也不在 v0002）
    fake = """Linux OSWbb v8.0.0
zzz ***Mon Jan 1 00:00:00 CST 2026
avg-cpu:  %user   %nice %system %iowait  %steal   %idle
           1.00    0.00    0.50   30.00    0.00   68.50
Device            r/s     w/s     rkB/s   %util  new_col_a  new_col_b
sda               0.00    0.00     0.00   100.0  42.0       99.0
"""
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.dat.gz', delete=False) as f:
        with gzip.open(f, mode='wt', encoding='utf-8') as gz:
            gz.write(fake)
        path = f.name

    registry = IostatVersionRegistry()
    try:
        with pytest.raises(UnknownIostatFormat):
            registry.detect(path)
    finally:
        import os
        os.unlink(path)


def test_detect_rejects_device_header_subset_only():
    """device_header 是 v0001 的真子集（缺列）→ 不应误判为 v0001"""
    import gzip
    import tempfile
    from backend.parser.iostat import IostatVersionRegistry
    from backend.parser.iostat.exceptions import UnknownIostatFormat

    # banner 同 v0001，但 device_header 只有 3 列
    fake = """Linux OSWbb v7.3.3
zzz ***Mon Jan 1 00:00:00 CST 2026
avg-cpu:  %user   %nice %system %iowait  %steal   %idle
           1.00    0.00    0.50   30.00    0.00   68.50
Device:   r/s  w/s  %util
sda       0.00  0.00  0.00
"""
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.dat.gz', delete=False) as f:
        with gzip.open(f, mode='wt', encoding='utf-8') as gz:
            gz.write(fake)
        path = f.name

    registry = IostatVersionRegistry()
    try:
        with pytest.raises(UnknownIostatFormat):
            registry.detect(path)
    finally:
        import os
        os.unlink(path)


# ─── Slice 3: detect 算法正确路由 ─────────────────────────────────────


def test_detect_routes_v0001_to_v0001():
    """detect() 对 OSWbb banner 返回 v0001"""
    from backend.parser.iostat import IostatVersionRegistry
    registry = IostatVersionRegistry()
    ver = registry.detect(str(VERSIONS_DIR / 'v0001' / 'sample.dat.gz'))
    assert ver == 'v0001'


def test_detect_routes_v0002_to_v0002():
    """detect() 对 WQWbb banner 返回 v0002"""
    from backend.parser.iostat import IostatVersionRegistry
    registry = IostatVersionRegistry()
    ver = registry.detect(str(VERSIONS_DIR / 'v0002' / 'sample.dat.gz'))
    assert ver == 'v0002'


# ─── Slice 4: 未知格式归档 ────────────────────────────────────────────


def test_unknown_format_raises_and_archives(tmp_path, monkeypatch):
    """未知 banner → 抛 UnknownIostatFormat + 样本被复制到 pending 目录"""
    import gzip
    from backend.parser.iostat import IostatVersionRegistry
    from backend.parser.iostat.exceptions import UnknownIostatFormat

    # 用 monkeypatch 把 pending 目录重定向到 tmp_path，避免污染真实目录
    monkeypatch.setattr(
        'backend.parser.iostat.VERSIONS_DIR',
        VERSIONS_DIR,
    )

    # 构造一个 banner 不在已知 BANNER 集合里的文件
    unknown_file = tmp_path / 'unknown.dat.gz'
    with gzip.open(unknown_file, mode='wt') as f:
        f.write('Linux FOObar v9.9.9\n')
        f.write('zzz ***Mon Jan 1 00:00:00 CST 2026\n')
        f.write('avg-cpu:  %user   %nice %system %iowait  %steal   %idle\n')
        f.write('           1.00    0.00    0.50   30.00    0.00   68.50\n')
        f.write('Device:   r/s  w/s\n')
        f.write('sda       0.00  0.00\n')

    registry = IostatVersionRegistry()

    # 把 _archive_pending 内部路径重定向到 tmp_path
    def fake_archive(filepath, banner):
        import shutil
        from pathlib import Path
        from datetime import datetime
        import hashlib
        pending_dir = tmp_path / 'iostat-version' / 'pending'
        pending_dir.mkdir(parents=True, exist_ok=True)
        src = Path(filepath)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        with open(src, 'rb') as f:
            short = hashlib.md5(f.read(4096)).hexdigest()[:8]
        dst = pending_dir / f'sample_{ts}_{short}{src.suffix}'
        shutil.copy2(src, dst)
        return dst

    monkeypatch.setattr(registry, '_archive_pending', fake_archive)

    with pytest.raises(UnknownIostatFormat) as exc_info:
        registry.parse(str(unknown_file))

    exc = exc_info.value
    assert exc.banner is not None
    assert 'FOObar' in exc.banner
    assert exc.pending_path is not None
    # 样本被复制到 pending
    pending_files = list((tmp_path / 'iostat-version' / 'pending').iterdir())
    assert len(pending_files) == 1
    assert pending_files[0].suffix == '.gz'


# ─── Slice 5: /api/parse 走 registry（HTTP 端到端） ───────────────────


@pytest.fixture
def no_cache(monkeypatch):
    """HTTP 测试隔离：禁用 cache 读写，避免脏缓存污染测试结果"""
    monkeypatch.setattr('backend.cache.json_cache.get_cached', lambda fpath: None)
    monkeypatch.setattr('backend.cache.json_cache.save_cache', lambda fpath, data: None)
    yield


def test_api_parse_v0001_returns_devices(no_cache, tmp_path):
    """POST /api/parse 对 v0001 数据 → 200 + devices 非空"""
    from fastapi.testclient import TestClient
    from backend.main import app
    client = TestClient(app)

    # 复制 sample 到 tmp_path，避免污染真实目录
    import shutil
    sample_dir = tmp_path / 'v0001'
    sample_dir.mkdir()
    sample = sample_dir / 'sample.dat.gz'
    shutil.copy(str(VERSIONS_DIR / 'v0001' / 'sample.dat.gz'), str(sample))

    resp = client.post('/api/parse', json={
        'dir_path': str(sample_dir),
        'files': [str(sample)],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data['cycles_count'] > 0
    assert len(data['devices']) > 0


def test_api_parse_v0002_returns_devices(no_cache, tmp_path):
    """POST /api/parse 对 v0002 数据 → 200 + devices 非空"""
    from fastapi.testclient import TestClient
    from backend.main import app
    client = TestClient(app)

    import shutil
    sample_dir = tmp_path / 'v0002'
    sample_dir.mkdir()
    sample = sample_dir / 'sample.dat.gz'
    shutil.copy(str(VERSIONS_DIR / 'v0002' / 'sample.dat.gz'), str(sample))

    resp = client.post('/api/parse', json={
        'dir_path': str(sample_dir),
        'files': [str(sample)],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data['cycles_count'] > 0
    assert len(data['devices']) > 0


# ─── Slice 6: /api/iostat/versions + pending endpoints ───────────────


def test_api_iostat_versions_lists_known():
    """GET /api/iostat/versions 返回所有已注册版本"""
    from fastapi.testclient import TestClient
    from backend.main import app
    client = TestClient(app)

    resp = client.get('/api/iostat/versions')
    assert resp.status_code == 200
    data = resp.json()
    version_ids = {v['version'] for v in data['versions']}
    assert 'v0001' in version_ids
    assert 'v0002' in version_ids
    # 验证 manifest 字段都返回
    v0001 = next(v for v in data['versions'] if v['version'] == 'v0001')
    assert v0001['display_name'] == 'OSWbb 旧格式'
    assert v0001['banner'] == 'Linux OSWbb v7.3.3'
