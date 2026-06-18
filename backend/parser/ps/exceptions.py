"""
ps 工具专用异常。
"""


class UnknownPsFormat(Exception):
    """ps 文件 fingerprint 不匹配任何已知版本时抛出。"""

    def __init__(self, banner: str | None, ps_header: list[str] | None, pending_path: str):
        self.banner = banner
        self.ps_header = ps_header
        self.pending_path = pending_path
        super().__init__(
            f'未知 ps 格式：banner={banner!r}, ps_header={ps_header}'
        )
