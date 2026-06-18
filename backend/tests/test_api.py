"""
OSW-View API 测试
"""

import os
import pytest
from fastapi.testclient import TestClient
from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_dir():
    return '/root/projects/osw-view/log_source_dir/20260524_249/oswiostat'


class TestScanAPI:
    """GET /api/scan"""

    def test_scan_returns_file_list(self, client, sample_dir):
        """扫描目录返回 .dat.gz 文件列表"""
        resp = client.post('/api/scan', json={'path': sample_dir})
        assert resp.status_code == 200
        data = resp.json()
        assert 'files' in data
        assert isinstance(data['files'], list)
        assert len(data['files']) > 0
        assert all(f.endswith('.dat.gz') for f in data['files'])

    def test_scan_nonexistent_dir_returns_400(self, client):
        """不存在的目录返回 400"""
        resp = client.post('/api/scan', json={'path': '/nonexistent/path'})
        assert resp.status_code == 400


class TestParseAPI:
    """POST /api/parse"""

    def test_parse_returns_cycles_and_devices(self, client, sample_dir):
        """解析文件返回 cycles、devices、metrics"""
        # 先扫描获取文件列表
        scan_resp = client.post('/api/scan', json={'path': sample_dir})
        files = scan_resp.json()['files'][:1]  # 只取第一个文件

        resp = client.post('/api/parse', json={
            'dir_path': sample_dir,
            'files': files,
            'parser_type': 'iostat',
        })
        assert resp.status_code == 200
        data = resp.json()
        assert 'cycles_count' in data
        assert 'devices' in data
        assert 'metrics' in data
        assert 'cpu_metrics' in data
        assert 'data' in data
        assert data['cycles_count'] > 0
        assert len(data['devices']) > 0

    def test_parse_unknown_parser_returns_400(self, client, sample_dir):
        """未知解析器类型返回 400"""
        resp = client.post('/api/parse', json={
            'dir_path': sample_dir,
            'files': [],
            'parser_type': 'unknown',
        })
        assert resp.status_code == 400

    def test_parse_response_includes_matched_versions(self, client, sample_dir, monkeypatch):
        """解析响应包含 matched_versions: {version_id: [basenames]}"""
        # 隔离 cache：避免脏缓存影响
        monkeypatch.setattr('backend.cache.json_cache.get_cached', lambda fpath: None)
        monkeypatch.setattr('backend.cache.json_cache.save_cache', lambda fpath, data: None)

        scan_resp = client.post('/api/scan', json={'path': sample_dir})
        files = scan_resp.json()['files'][:2]

        resp = client.post('/api/parse', json={
            'dir_path': sample_dir,
            'files': files,
            'parser_type': 'iostat',
        })
        assert resp.status_code == 200
        data = resp.json()
        assert 'matched_versions' in data, '响应应包含 matched_versions 字段'
        # 这些样本来自 v0001（OSWbb）目录
        assert 'v0001' in data['matched_versions']
        assert len(data['matched_versions']['v0001']) == len(files)
        # matched_versions 返回 basename（与 scan 全路径解耦，前端按 basename 映射）
        expected_basenames = {os.path.basename(f) for f in files}
        assert set(data['matched_versions']['v0001']) == expected_basenames

    def test_parse_cache_hit_reports_version_from_cache(self, client, sample_dir, monkeypatch):
        """缓存命中：matched_versions 应从 cache 读取 version 字段（避免重复 detect）"""
        # 用 stub cache：第一次解析后保存到内存 dict，第二次走 cache
        cache_store: dict[str, dict] = {}

        def fake_get(fpath):
            return cache_store.get(fpath)

        def fake_save(fpath, data):
            cache_store[fpath] = data

        monkeypatch.setattr('backend.cache.json_cache.get_cached', fake_get)
        monkeypatch.setattr('backend.cache.json_cache.save_cache', fake_save)

        scan_resp = client.post('/api/scan', json={'path': sample_dir})
        files = scan_resp.json()['files'][:1]

        # 第一次解析：填缓存
        resp1 = client.post('/api/parse', json={
            'dir_path': sample_dir, 'files': files, 'parser_type': 'iostat',
        })
        assert resp1.status_code == 200
        assert 'v0001' in resp1.json()['matched_versions']
        # 缓存里有 version 字段
        assert any('version' in d for d in cache_store.values())

        # 第二次解析：全走缓存，matched_versions 应仍报版本
        resp2 = client.post('/api/parse', json={
            'dir_path': sample_dir, 'files': files, 'parser_type': 'iostat',
        })
        assert resp2.status_code == 200
        assert resp2.json()['matched_versions'].get('v0001') == \
            [os.path.basename(files[0])]

    def test_parse_cache_hit_without_version_falls_back_to_detect(
        self, client, sample_dir, monkeypatch,
    ):
        """旧缓存没有 version 字段 → 走 detect 兜底，不应被遗漏"""
        # stub cache：模拟旧缓存（只有 cycles，没有 version）
        cache_store: dict[str, dict] = {}

        def fake_get(fpath):
            return cache_store.get(fpath)

        monkeypatch.setattr('backend.cache.json_cache.get_cached', fake_get)
        monkeypatch.setattr('backend.cache.json_cache.save_cache',
                            lambda fpath, data: cache_store.__setitem__(fpath, data))

        scan_resp = client.post('/api/scan', json={'path': sample_dir})
        files = scan_resp.json()['files'][:1]
        fpath = files[0]

        # 预先写入一个不带 version 的"旧缓存"
        cache_store[fpath] = {'cycles': []}
        assert 'version' not in cache_store[fpath]  # 确认是旧格式

        resp = client.post('/api/parse', json={
            'dir_path': sample_dir, 'files': files, 'parser_type': 'iostat',
        })
        assert resp.status_code == 200
        # 兜底：matched_versions 应仍报版本（通过 detect 重新拿到）
        assert resp.json()['matched_versions'].get('v0001') == \
            [os.path.basename(files[0])]

    def test_parse_multiple_versions_group_correctly(self, client, monkeypatch, tmp_path):
        """跨版本混合解析：matched_versions 应按 version_id 分组"""
        import shutil
        from backend.tests.test_iostat_versions import VERSIONS_DIR

        # 准备混合目录：1 个 v0001 + 1 个 v0002
        mixed_dir = tmp_path / 'mixed'
        mixed_dir.mkdir()
        v1 = mixed_dir / 'v1.dat.gz'
        v2 = mixed_dir / 'v2.dat.gz'
        shutil.copy(str(VERSIONS_DIR / 'v0001' / 'sample.dat.gz'), str(v1))
        shutil.copy(str(VERSIONS_DIR / 'v0002' / 'sample.dat.gz'), str(v2))

        monkeypatch.setattr('backend.cache.json_cache.get_cached', lambda fpath: None)
        monkeypatch.setattr('backend.cache.json_cache.save_cache', lambda fpath, data: None)

        resp = client.post('/api/parse', json={
            'dir_path': str(mixed_dir),
            'files': [str(v1), str(v2)],
            'parser_type': 'iostat',
        })
        assert resp.status_code == 200
        mv = resp.json()['matched_versions']
        assert mv.get('v0001') == ['v1.dat.gz']
        assert mv.get('v0002') == ['v2.dat.gz']
