"""
解析器基类。
所有解析器（如 iostat、ps、top）都实现此接口。
"""

import gzip
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ParsedCycle:
    """一个采集周期的解析结果"""
    timestamp: str  # ISO 格式时间字符串
    cpu: dict[str, float] = field(default_factory=dict)
    devices: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ParseResult:
    """解析结果"""
    cycles: list[ParsedCycle]


class BaseParser(ABC):
    """解析器基类"""

    # 解析器名称，如 "iostat", "ps", "top"
    NAME: str = ""

    # 列名 → 标准化字段名 映射表
    COLUMN_MAPPING: dict[str, str] = {}

    def parse_file(self, filepath: str) -> ParseResult:
        """解析单个 .dat.gz 文件"""
        cycles: list[ParsedCycle] = []
        current_cycle: dict | None = None

        if filepath.endswith('.gz'):
            f = gzip.open(filepath, mode='rt', encoding='utf-8', errors='replace')
        else:
            f = open(filepath, encoding='utf-8', errors='replace')

        with f:
            for raw_line in f:
                line = raw_line.rstrip()
                result = self._parse_line(line, current_cycle)
                # False = 跳过此行（哨兵），不追加数据
                if result is False:
                    continue
                if result is not None:
                    if current_cycle is not None:
                        cycles.append(self._finalize_cycle(current_cycle))
                    current_cycle = result
                elif current_cycle is not None:
                    self._append_to_cycle(current_cycle, line)

        if current_cycle is not None:
            cycles.append(self._finalize_cycle(current_cycle))

        return ParseResult(cycles=cycles)

    @abstractmethod
    def _parse_line(self, line: str, current_cycle: dict | None) -> dict | None | bool:
        """
        解析一行。
        如果遇到新的 cycle 起始行，返回 cycle 元数据；否则返回 None。
        """
        ...

    @abstractmethod
    def _append_to_cycle(self, cycle: dict, line: str) -> None:
        """将一行数据追加到当前 cycle"""
        ...

    def _finalize_cycle(self, cycle: dict) -> ParsedCycle:
        """将原始 cycle dict 转换为 ParsedCycle（子类必须实现）"""
        raise NotImplementedError

    def _normalize_device_name(self, name: str) -> str:
        """设备名归一化（子类可覆盖）"""
        return name.strip()

    def _map_column(self, raw_name: str) -> str:
        """将原始列名映射为标准化字段名"""
        return self.COLUMN_MAPPING.get(raw_name.strip(), raw_name.strip())
