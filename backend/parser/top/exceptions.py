"""
top 工具专用异常。
"""


class UnknownTopFormat(Exception):
    """top 文件 fingerprint 不匹配任何已知版本时抛出。"""

    def __init__(self, banner: str | None, top_header: list[str] | None, pending_path: str):
        self.banner = banner
        self.top_header = top_header
        self.pending_path = pending_path
        super().__init__(
            f'未知 top 格式：banner={banner!r}, top_header={top_header}'
        )
