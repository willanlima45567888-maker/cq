"""
netstat 工具专用异常。
"""


class UnknownNetstatFormat(Exception):
    """netstat 文件 fingerprint 不匹配任何已知版本时抛出。"""

    def __init__(
        self,
        banner: str | None,
        section_marker: str | None,
        pending_path: str,
    ):
        self.banner = banner
        self.section_marker = section_marker
        self.pending_path = pending_path
        super().__init__(
            f'未知 netstat 格式：banner={banner!r}, section_marker={section_marker!r}'
        )
