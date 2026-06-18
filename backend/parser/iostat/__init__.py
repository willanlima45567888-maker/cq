"""
iostat 版本注册表。

按格式版本（v0001、v0002...）管理多个 parser，每个版本在
versions/<id>/ 目录下，包含 parser.py、manifest.json 和 sample.dat.gz。
"""

from pathlib import Path


VERSIONS_DIR = Path(__file__).parent / 'versions'


def _fingerprints_match(file_fp: dict, known_fp: dict) -> bool:
    """fingerprint 严格匹配：banner 完全相等 + 两个 header 集合相等"""
    if file_fp.get('banner') != known_fp.get('banner'):
        return False
    file_dev = set(file_fp.get('device_header') or [])
    known_dev = set(known_fp.get('device_header') or [])
    if file_dev != known_dev:
        return False
    file_cpu = set(file_fp.get('cpu_header') or [])
    known_cpu = set(known_fp.get('cpu_header') or [])
    if file_cpu != known_cpu:
        return False
    return True


class IostatVersionRegistry:
    """iostat 格式版本注册表，负责 detect + dispatch + 未知格式归档。"""

    def __init__(self, versions_dir: Path | None = None) -> None:
        self.versions_dir = versions_dir or VERSIONS_DIR
        self.versions: dict[str, type] = {}  # version_id -> parser class
        self.fingerprints: dict[str, dict] = {}  # version_id -> fingerprint json
        self._load_all()

    def _load_all(self) -> None:
        """importlib 扫描 versions/ 目录，加载所有 VxxxxParser + 读取 fingerprint.json。

        按版本号倒序加载（新版本优先），这样 fingerprint 跟旧版本完全相同的占位
        版本（如 v0003 是 v0002 镜像）能优先命中，而不是被旧版本"抢"走。
        """
        import importlib
        import json
        for entry in sorted(self.versions_dir.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            parser_path = entry / 'parser.py'
            fingerprint_path = entry / 'fingerprint.json'
            if not parser_path.exists() or not fingerprint_path.exists():
                continue
            mod = importlib.import_module(
                f'backend.parser.iostat.versions.{entry.name}.parser'
            )
            cls_name = 'V' + entry.name[1:].upper() + 'Parser'
            cls = getattr(mod, cls_name, None)
            if cls is not None:
                self.versions[cls.VERSION] = cls
                fp = json.loads(fingerprint_path.read_text(encoding='utf-8'))
                self.fingerprints[cls.VERSION] = fp

    def list_versions(self) -> list[dict]:
        """返回所有已注册版本的 manifest 列表。"""
        result = []
        for entry in sorted(self.versions_dir.iterdir()):
            manifest_path = entry / 'manifest.json'
            if not manifest_path.exists():
                continue
            import json
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                fp = self.fingerprints.get(manifest['version'], {})
                manifest['banner'] = fp.get('banner')
                # active 字段缺省视为 true（向后兼容旧 manifest）
                manifest.setdefault('active', True)
                result.append(manifest)
            except (json.JSONDecodeError, KeyError):
                continue
        return result

    def parse(self, filepath: str):
        """根据文件 fingerprint 自动匹配版本并解析。"""
        from backend.parser.base import ParseResult
        ver = self.detect(filepath)
        return self.versions[ver]().parse_file(filepath)

    def detect(self, filepath: str) -> str:
        """提取上传文件的 fingerprint，跟每个 v000x/fingerprint.json 严格匹配。

        匹配规则（全部满足）：
          1. banner 完全相等（字符串 ==）
          2. device_header 集合相等（顺序无关）
          3. cpu_header 集合相等（顺序无关）

        任一候选都不匹配 → 抛 UnknownIostatFormat + 归档样本。
        """
        from backend.parser.iostat.fingerprint import extract_fingerprint
        from backend.parser.iostat.exceptions import UnknownIostatFormat

        file_fp = extract_fingerprint(filepath)

        for ver_id, known_fp in self.fingerprints.items():
            if _fingerprints_match(file_fp, known_fp):
                return ver_id

        banner = file_fp.get('banner')
        pending_path = self._archive_pending(filepath, banner)
        raise UnknownIostatFormat(
            banner=banner,
            header_columns=file_fp.get('device_header'),
            pending_path=str(pending_path),
        )

    # ─── 辅助方法 ───────────────────────────────────────────────────

    def _peek(self, filepath: str, n: int) -> str:
        import gzip
        if filepath.endswith('.gz'):
            with gzip.open(filepath, mode='rt', encoding='utf-8', errors='replace') as f:
                return f.read(n)
        with open(filepath, encoding='utf-8', errors='replace') as f:
            return f.read(n)

    def _extract_banner(self, text: str) -> str | None:
        import re
        m = re.search(r'Linux\s+(\S+)\s+v[\d.]+', text)
        return m.group(0) if m else None

    def _extract_header_columns(self, text: str) -> list[str] | None:
        import re
        # 找第一个 Device[ :] 开头的行
        m = re.search(r'^Device\s*[:]?\s+(.+)$', text, re.MULTILINE)
        if not m:
            return None
        return m.group(1).split()

    def _archive_pending(self, filepath: str, banner: str | None) -> Path:
        """把未知格式样本复制到 iostat-version/pending/，返回归档路径。"""
        import shutil
        from datetime import datetime
        import hashlib

        # pending 目录：项目根 /iostat-version/pending/
        # __file__ = backend/parser/iostat/__init__.py
        # .parent.parent.parent.parent = 项目根
        project_root = Path(__file__).parent.parent.parent.parent
        pending_dir = project_root / 'iostat-version' / 'pending'
        pending_dir.mkdir(parents=True, exist_ok=True)

        src = Path(filepath)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        with open(src, 'rb') as f:
            short = hashlib.md5(f.read(4096)).hexdigest()[:8]
        dst = pending_dir / f'sample_{ts}_{short}{src.suffix}{".gz" if str(src).endswith(".gz") and not str(src).endswith(".dat.gz") else ""}'
        # 简化：直接保留原后缀
        if str(src).endswith('.dat.gz'):
            dst = pending_dir / f'sample_{ts}_{short}.dat.gz'
        else:
            dst = pending_dir / f'sample_{ts}_{short}{src.suffix}'

        shutil.copy2(src, dst)
        return dst


# ─── 兼容层：让 main.py 旧 import 不崩（Slice 5 删除） ──────────────
from backend.parser.iostat.versions.v0001.parser import V0001Parser  # noqa: E402
IostatParser = V0001Parser  # 旧 main.py: from .parser.iostat import IostatParser
