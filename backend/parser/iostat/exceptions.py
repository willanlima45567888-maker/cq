"""
iostat 解析器相关异常。
"""


class UnknownIostatFormat(Exception):
    """无法识别 iostat 文件格式（无 BANNER 匹配）时抛出。

    Attributes:
        banner: 从文件首行提取的 Linux banner（如 "Linux XYZbb v8.0"），可能为 None
        header_columns: Device header 行的列名列表（用于诊断），可能为 None
        pending_path: 样本文件被复制到的 pending 路径
    """

    def __init__(self, banner: str | None, header_columns: list[str] | None, pending_path: str):
        self.banner = banner
        self.header_columns = header_columns
        self.pending_path = pending_path
        super().__init__(
            f'未识别 iostat 格式 (banner={banner!r}, pending={pending_path!r})'
        )
