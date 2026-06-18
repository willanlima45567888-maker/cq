"""
V0001Parser — OSWbb 旧格式

格式定义从 fingerprint.json 读取（device_header / cpu_header / column_mapping），
本文件只保留解析算法（状态机）。
"""

import re
from datetime import datetime
from pathlib import Path

from backend.parser.base import BaseParser


def _load_fingerprint() -> dict:
    """从同目录的 fingerprint.json 读取格式定义"""
    import json
    fp_path = Path(__file__).parent / 'fingerprint.json'
    return json.loads(fp_path.read_text(encoding='utf-8'))


class V0001Parser(BaseParser):
    NAME = 'iostat-v0001'
    VERSION = 'v0001'

    CYCLE_PATTERN = re.compile(r'zzz\s+\*\*\*(.+)')
    CPU_HEADER_PATTERN = re.compile(r'^avg-cpu:')
    DEVICE_HEADER_PATTERN = re.compile(r'^Device:')

    def __init__(self) -> None:
        self._fp = _load_fingerprint()
        self.COLUMN_MAPPING: dict[str, str] = self._fp['column_mapping']

    def _map_column(self, raw_name: str) -> str:
        return self.COLUMN_MAPPING.get(raw_name.strip(), raw_name.strip())

    def _parse_line(self, line: str, current_cycle: dict | None) -> dict | None | bool:
        m = self.CYCLE_PATTERN.match(line)
        if m:
            ts_str = m.group(1).strip()
            dt = self._parse_timestamp(ts_str)
            return {
                'timestamp': dt.isoformat() if dt else ts_str,
                'raw_timestamp': ts_str,
                'cpu': {},
                'devices': [],
                '_section': None,
            }

        if self.CPU_HEADER_PATTERN.match(line):
            if current_cycle is not None:
                current_cycle['_section'] = 'cpu'
            return None

        if self.DEVICE_HEADER_PATTERN.match(line):
            if current_cycle is not None:
                parts = line.split()
                if len(parts) > 1:
                    current_cycle['_device_header'] = parts[1:]
                current_cycle['_section'] = 'device'
            return False

        return None

    def _append_to_cycle(self, cycle: dict, line: str) -> None:
        section = cycle.get('_section')
        if section == 'cpu':
            self._parse_cpu_line(cycle, line)
        elif section == 'device':
            self._parse_device_line(cycle, line)

    def _parse_cpu_line(self, cycle: dict, line: str) -> None:
        parts = line.split()
        if len(parts) < 6:
            return
        try:
            cycle['cpu'] = {
                '%user': float(parts[0]),
                '%nice': float(parts[1]),
                '%system': float(parts[2]),
                '%iowait': float(parts[3]),
                '%steal': float(parts[4]),
                '%idle': float(parts[5]),
            }
        except (ValueError, IndexError):
            pass

    def _parse_device_line(self, cycle: dict, line: str) -> None:
        parts = line.split()
        if len(parts) < 2:
            return
        device_name = parts[0]
        header = cycle.get('_device_header', [])
        if not header:
            return
        try:
            device_data: dict = {'device': device_name}
            for i, col_name in enumerate(header):
                std_name = self._map_column(col_name)
                if i + 1 < len(parts):
                    try:
                        device_data[std_name] = float(parts[i + 1])
                    except ValueError:
                        device_data[std_name] = None
            cycle['devices'].append(device_data)
        except (ValueError, IndexError):
            pass

    def _finalize_cycle(self, cycle: dict):
        from backend.parser.base import ParsedCycle
        return ParsedCycle(
            timestamp=cycle['timestamp'],
            cpu=cycle.get('cpu', {}),
            devices=cycle.get('devices', []),
        )

    def _parse_timestamp(self, ts_str: str) -> datetime | None:
        try:
            ts_clean = re.sub(r'\s+(CST|CDT)\s+', ' ', ts_str)
            return datetime.strptime(ts_clean, '%a %b %d %H:%M:%S %Y')
        except ValueError:
            return None
