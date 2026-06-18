"""
V0001Parser — WQWbb ps 标准格式

格式定义从 fingerprint.json 读取（ps_header / column_mapping），
本文件只保留解析入口（委托给通用 parser.parse_ps_file）。
"""

import json
from pathlib import Path

from ...parser import parse_ps_file, PsParseResult


def _load_fingerprint() -> dict:
    fp_path = Path(__file__).parent / 'fingerprint.json'
    return json.loads(fp_path.read_text(encoding='utf-8'))


class V0001Parser:
    NAME = 'ps-v0001'
    VERSION = 'v0001'

    def __init__(self) -> None:
        self._fp = _load_fingerprint()

    def parse_file(self, filepath: str) -> PsParseResult:
        return parse_ps_file(
            filepath,
            ps_header=self._fp['ps_header'],
            column_mapping=self._fp.get('column_mapping'),
        )
