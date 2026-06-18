"""
netstat 工具（OSW netstat 日志分析）。

子模块：
  - fingerprint：提取 banner / cycle_pattern / section_marker
  - parser：通用 netstat 状态机（按 cycle 切分 + 解析接口块 + 解析 kernel counters）
  - registry：版本注册表（detect/parse，倒序加载）
  - exceptions：UnknownNetstatFormat
  - analyzer：聚合分析（接口时序 + kernel counters + TOP N 接口）
  - versions/<id>/：各 netstat 格式版本的 fingerprint + manifest + parser
"""

from .fingerprint import CYCLE_PATTERN, extract_fingerprint
from .parser import (
    NetstatCycle,
    NetstatInterface,
    NetstatParseResult,
    parse_netstat_file,
)
from .registry import NetstatVersionRegistry
from .exceptions import UnknownNetstatFormat
from .analyzer import analyze_cycles

__all__ = [
    'CYCLE_PATTERN',
    'NetstatCycle',
    'NetstatInterface',
    'NetstatParseResult',
    'NetstatVersionRegistry',
    'UnknownNetstatFormat',
    'analyze_cycles',
    'extract_fingerprint',
    'parse_netstat_file',
]
