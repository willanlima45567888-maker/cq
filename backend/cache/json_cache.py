"""
JSON 文件缓存（按文件路径 hash 存 cache_data/）。

注意：ps 大文件（150MB+ 源文件，parse 后 1.5GB 内存 dict）的完整 cycles
不再走这个缓存——会撑爆内存。save_cache 时如果数据太大（>200MB），会跳过
（只保留 version 字段），下次 parse 直接从源文件重新读。

summary 数据独立存到 cache_data/summary/ 目录（轻量、毫秒级）。
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any


CACHE_DIR = Path(__file__).parent.parent / 'cache_data'

# 单个 cache 文件超过这个大小就不再保存 cycles 完整数据（避免磁盘+内存爆）
# ps 工具的 cycles 完整数据会超 200MB，不存；iostat 小（<10MB），可存
MAX_CACHE_FILE_SIZE_BYTES = 200 * 1024 * 1024  # 200MB


def _file_hash(filepath: str) -> str:
    """计算文件内容的 MD5 哈希（只取前 4KB 用于快速判断）"""
    with open(filepath, 'rb') as f:
        chunk = f.read(4096)
    return hashlib.md5(chunk).hexdigest()[:12]


def _get_cache_path(source_path: str) -> Path:
    """根据源文件路径生成缓存文件路径"""
    source_name = os.path.basename(source_path)
    # 创建安全的哈希子目录
    short_hash = hashlib.md5(source_path.encode()).hexdigest()[:8]
    subdir = CACHE_DIR / short_hash
    subdir.mkdir(parents=True, exist_ok=True)
    return subdir / f'{source_name}.json'


def get_cached(source_path: str) -> dict | None:
    """
    获取缓存。
    如果缓存存在且文件未变化，返回缓存内容；否则返回 None。
    """
    cache_path = _get_cache_path(source_path)
    if not cache_path.exists():
        return None

    # 如果 cache 文件太大（>200MB），跳过读（避免 1.5GB 内存开销）
    try:
        if cache_path.stat().st_size > MAX_CACHE_FILE_SIZE_BYTES:
            return None
    except OSError:
        return None

    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def save_cache(source_path: str, data: dict) -> bool:
    """
    保存解析结果到缓存。

    返回 True 表示成功写入；False 表示跳过（数据太大不存）。
    跳过后下次 parse 会重新从源文件读取。
    """
    cache_path = _get_cache_path(source_path)

    # 先序列化测大小
    try:
        # 临时序列化到内存估算大小
        serialized = json.dumps(data, ensure_ascii=False, indent=2)
        size = len(serialized.encode('utf-8'))
    except (TypeError, ValueError):
        return False

    if size > MAX_CACHE_FILE_SIZE_BYTES:
        # 数据太大，跳过 cache（但 version 字段还是值得存；存到小文件）
        return _save_version_only(source_path, data)

    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            f.write(serialized)
        return True
    except OSError:
        return False


def _save_version_only(source_path: str, data: dict) -> bool:
    """数据太大时，只存 version/parser_type 字段（不存 cycles）"""
    cache_path = _get_cache_path(source_path)
    minimal = {k: v for k, v in data.items() if k in ('version', 'parser_type')}
    if not minimal:
        return False
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(minimal, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def clear_cache(source_path: str | None = None) -> None:
    """
    清除缓存。指定 source_path 时只清除该文件的缓存，否则清除所有缓存。
    """
    if source_path:
        cache_path = _get_cache_path(source_path)
        if cache_path.exists():
            cache_path.unlink()
    else:
        import shutil
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
