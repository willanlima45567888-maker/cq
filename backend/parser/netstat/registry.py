"""
netstat 格式版本注册表（类似 top/registry）。

按格式版本（v0001、v0002...）管理多个 parser，每个版本在
versions/<id>/ 目录下，包含 parser.py、manifest.json 和 fingerprint.json。

与 top 不同的两点：
  1. fingerprint 比对 3 项：banner（支持 glob）/ cycle_pattern / section_marker
  2. section_marker 固定 '#kernel'（netstat 特有）
"""

import fnmatch
import importlib
import json
from pathlib import Path

from .exceptions import UnknownNetstatFormat
from .fingerprint import CYCLE_PATTERN, extract_fingerprint


VERSIONS_DIR = Path(__file__).parent / 'versions'


def _banner_match(file_banner: str, known_banner: str) -> bool:
    """banner 匹配：known 含 glob 字符（* ? [）时用 fnmatch，否则严格相等。"""
    if not known_banner:
        return not file_banner
    if any(c in known_banner for c in '*?['):
        return fnmatch.fnmatchcase(file_banner, known_banner)
    return file_banner == known_banner


def _fingerprints_match(file_fp: dict, known_fp: dict) -> bool:
    """fingerprint 匹配：banner（支持 glob）+ cycle_pattern + section_marker 全部相等"""
    if not _banner_match(file_fp.get('banner') or '', known_fp.get('banner') or ''):
        return False
    if file_fp.get('cycle_pattern') != known_fp.get('cycle_pattern'):
        return False
    if file_fp.get('section_marker') != known_fp.get('section_marker'):
        return False
    return True


class NetstatVersionRegistry:
    """netstat 格式版本注册表，负责 detect + dispatch + 未知格式归档。"""

    def __init__(self, versions_dir: Path | None = None) -> None:
        self.versions_dir = versions_dir or VERSIONS_DIR
        self.versions: dict[str, type] = {}  # version_id -> parser class
        self.fingerprints: dict[str, dict] = {}  # version_id -> fingerprint json
        self._load_all()

    def _load_all(self) -> None:
        """importlib 扫描 versions/ 目录，加载所有 VxxxxParser + 读取 fingerprint.json。

        按版本号倒序加载（新版本优先）。
        """
        for entry in sorted(self.versions_dir.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            parser_path = entry / 'parser.py'
            fingerprint_path = entry / 'fingerprint.json'
            if not parser_path.exists() or not fingerprint_path.exists():
                continue
            mod = importlib.import_module(
                f'backend.parser.netstat.versions.{entry.name}.parser'
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
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                fp = self.fingerprints.get(manifest['version'], {})
                manifest['banner'] = fp.get('banner')
                manifest['section_marker'] = fp.get('section_marker')
                manifest.setdefault('active', True)
                result.append(manifest)
            except (json.JSONDecodeError, KeyError):
                continue
        return result

    def parse(self, filepath: str):
        """根据文件 fingerprint 自动匹配版本并解析。"""
        ver = self.detect(filepath)
        return self.versions[ver]().parse_file(filepath)

    def detect(self, filepath: str) -> str:
        """提取上传文件的 fingerprint，跟每个 v000x/fingerprint.json 匹配。

        匹配规则（全部满足）：
          1. banner：严格相等，或 known 含 glob 字符（* ? [）时按 fnmatch 匹配
          2. cycle_pattern 字符串相等
          3. section_marker 字符串相等

        任一候选都不匹配 → 抛 UnknownNetstatFormat + 归档样本。
        """
        file_fp = extract_fingerprint(filepath)

        for ver_id, known_fp in self.fingerprints.items():
            if _fingerprints_match(file_fp, known_fp):
                return ver_id

        pending_path = self._archive_pending(filepath, file_fp)
        raise UnknownNetstatFormat(
            banner=file_fp.get('banner'),
            section_marker=file_fp.get('section_marker'),
            pending_path=str(pending_path),
        )

    # ─── 辅助方法 ──────────────────────────────────────────────

    def _archive_pending(self, filepath: str, file_fp: dict) -> Path:
        """把未知格式样本复制到 pending/ 目录，返回归档路径。

        pending 目录：项目根 /iostat-version/pending/（与 ps/top 共用）
        """
        import shutil
        from datetime import datetime

        project_root = Path(__file__).parent.parent.parent.parent
        pending_dir = project_root / 'iostat-version' / 'pending'
        pending_dir.mkdir(parents=True, exist_ok=True)

        src = Path(filepath)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        # 用 banner 前缀作为 hint
        banner = file_fp.get('banner') or 'unknown'
        short = ''.join(c for c in banner if c.isalnum())[:8].lower() or 'sample'
        suffix = '.dat.gz' if str(src).endswith('.dat.gz') else src.suffix
        dst = pending_dir / f'netstat_{ts}_{short}{suffix}'

        shutil.copy2(src, dst)
        return dst
