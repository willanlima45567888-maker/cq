"""
top 工具（OSW top 日志分析）。

子模块：
  - fingerprint：从 top 文件提取 banner / cycle_pattern / top_header
  - parser：通用 top 状态机（按 cycle 切分 + 解析每行进程 + 解析系统摘要）
  - registry：版本注册表（detect/parse，倒序加载）
  - exceptions：UnknownTopFormat
  - analyzer：聚合分析（系统指标趋势 + 进程分类 + TOP N + 用户分布）
  - versions/<id>/：各 top 格式版本的 fingerprint + manifest + parser
"""

from .fingerprint import CYCLE_PATTERN, extract_fingerprint
from .parser import (
    TopCycle,
    TopParseResult,
    TopProcess,
    TopSummary,
    parse_top_file,
)
from .registry import TopVersionRegistry
from .exceptions import UnknownTopFormat
from .analyzer import analyze_cycles


__all__ = [
    'CYCLE_PATTERN',
    'TopCycle',
    'TopParseResult',
    'TopProcess',
    'TopSummary',
    'TopVersionRegistry',
    'UnknownTopFormat',
    'analyze_cycles',
    'extract_fingerprint',
    'parse_top_file',
]
