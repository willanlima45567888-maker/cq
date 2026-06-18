"""
V0002Parser — OSWbb top 标准格式

格式定义从 fingerprint.json 读取（top_header / column_mapping），
本文件只保留解析入口（委托给通用 parser.parse_top_file）。

与 v0001 的区别：banner 变体（Linux OSWbb v22.1.0AHF 等），
cycle 结构和 top_header 完全一致。
"""

import json
from pathlib import Path

from ...parser import parse_top_file, TopParseResult


def _load_fingerprint() -> dict:
    fp_path = Path(__file__).parent / 'fingerprint.json'
    return json.loads(fp_path.read_text(encoding='utf-8'))


class V0002Parser:
    NAME = 'top-v0002'
    VERSION = 'v0002'

    def __init__(self) -> None:
        self._fp = _load_fingerprint()

    def parse_file(self, filepath: str) -> TopParseResult:
        return parse_top_file(
            filepath,
            top_header=self._fp['top_header'],
            column_mapping=self._fp.get('column_mapping'),
        )
