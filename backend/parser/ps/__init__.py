"""
ps 工具（OSW ps 日志分析）。

子模块：
  - fingerprint：从 ps 文件提取 banner / cycle_pattern / ps_header
  - parser：通用 ps 状态机（按 cycle 切分 + 解析每行进程）
  - registry：版本注册表（detect/parse，倒序加载）
  - exceptions：UnknownPsFormat
  - versions/<id>/：各 ps 格式版本的 fingerprint + manifest + parser
"""

from .fingerprint import CYCLE_PATTERN, extract_fingerprint
from .parser import PsCycle, PsParseResult, PsProcess, parse_ps_file
from .registry import PsVersionRegistry
from .exceptions import UnknownPsFormat


__all__ = [
    'CYCLE_PATTERN',
    'PsCycle',
    'PsParseResult',
    'PsProcess',
    'PsVersionRegistry',
    'UnknownPsFormat',
    'extract_fingerprint',
    'parse_ps_file',
]
