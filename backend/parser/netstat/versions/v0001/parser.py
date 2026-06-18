"""
V0001Parser — OSWbb netstat 标准格式

格式定义从 fingerprint.json 读取（cycle_pattern + section_marker），
本文件只保留解析入口（委托给通用 parser.parse_netstat_file）。
"""

import json
from pathlib import Path

from ...parser import parse_netstat_file, NetstatParseResult


def _load_fingerprint() -> dict:
    fp_path = Path(__file__).parent / 'fingerprint.json'
    return json.loads(fp_path.read_text(encoding='utf-8'))


class V0001Parser:
    NAME = 'netstat-v0001'
    VERSION = 'v0001'

    def __init__(self) -> None:
        self._fp = _load_fingerprint()

    def parse_file(self, filepath: str) -> NetstatParseResult:
        return parse_netstat_file(
            filepath,
            section_marker=self._fp.get('section_marker', '#kernel'),
        )
