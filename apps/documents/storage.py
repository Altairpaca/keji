"""存储抽象层（ADR-002）：StorageBackend 接口 + LocalDiskStorage 实现。

接口以「存储键」为参数，不暴露文件系统路径；错误以自定义异常表达，
不向调用方抛裸 OSError 细节。存储键统一为 UUID，带两级分片前缀，
形如 ``originals/<uuid4 前 2 位>/<uuid4>``，避免单目录文件膨胀。

路径穿越防护（docs/security.md §4）收敛在本模块内部的 ``_safe_join``：
含 ``..`` / 绝对路径 / 空段 / 反斜杠的键一律拒绝。本地写采用临时文件 +
``os.replace`` 原子改名，写一半失败不残留半成品。
"""

import os
import shutil
import tempfile
import uuid
from abc import ABC, abstractmethod
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO

from django.conf import settings


class StorageError(Exception):
    """存储层统一异常（ADR-002 实现要点：不暴露裸 OSError 细节）。"""


class StorageKeyError(ValueError, StorageError):
    """非法存储键：路径穿越 / 绝对路径 / 危险字符。"""


class StorageBackend(ABC):
    """存储后端抽象接口（ADR-002）。

    - ``save``：把流式内容写入 key（实现需保证原子与临时文件清理）；
    - ``open``：返回可读二进制流，键不存在抛 ``StorageError``；
    - ``exists`` / ``delete`` / ``size``：探测 / 删除（幂等）/ 字节数。
    """

    @abstractmethod
    def save(self, key: str, content: BinaryIO) -> None: ...

    @abstractmethod
    def open(self, key: str) -> BinaryIO: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def size(self, key: str) -> int: ...


def _safe_join(root: Path, key: str) -> Path:
    """把存储键解析为 root 下的安全路径。

    拒绝绝对路径、``..`` 穿越、空路径段与反斜杠（Windows 分隔符），
    并对最终路径做 resolve 后二次校验，防 Unicode 等价绕过。
    """
    if not key or key.startswith("/") or key.startswith("\\"):
        raise StorageKeyError(f"非法存储键：{key!r}")
    parts = key.split("/")
    if any(part in ("", ".", "..") or "\\" in part for part in parts):
        raise StorageKeyError(f"非法存储键：{key!r}")
    path = root.joinpath(*parts)
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise StorageKeyError(f"存储键越界：{key!r}")
    return path


class LocalDiskStorage(StorageBackend):
    """本地磁盘实现：根目录 ``settings.MEDIA_ROOT``，键形如
    ``originals/<uuid4 前 2 位>/<uuid4>``。写入先落临时文件再原子改名。"""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        return _safe_join(self.root, key)

    def save(self, key: str, content: BinaryIO) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".part")
        try:
            with os.fdopen(fd, "wb") as tmp:
                shutil.copyfileobj(content, tmp, length=1024 * 1024)
                tmp.flush()
                os.fsync(tmp.fileno())
            # 同目录内 rename，原子替换，杜绝并发 / 中断残留半成品
            os.replace(tmp_name, path)
        except BaseException:
            with suppress(FileNotFoundError):
                os.unlink(tmp_name)
            raise

    def open(self, key: str) -> BinaryIO:
        path = self._path(key)
        if not self.exists(key):
            raise StorageError(f"文件不存在：{key}")
        return path.open("rb")

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        """幂等删除（对齐对象存储语义）：键不存在时静默成功。"""
        with suppress(FileNotFoundError):
            self._path(key).unlink()

    def size(self, key: str) -> int:
        path = self._path(key)
        try:
            return path.stat().st_size
        except FileNotFoundError:
            raise StorageError(f"文件不存在：{key}") from None


def new_storage_key() -> str:
    """生成原图存储键：``originals/<uuid4 前 2 位>/<uuid4>``（ADR-002/005）。

    键内绝不含客户姓名或原始文件名；原始文件名仅作元数据存于数据库。
    """
    uid = str(uuid.uuid4())
    return f"originals/{uid[:2]}/{uid}"


# 模块级默认存储单例：settings 可切换 S3 实现（ADR-002 预留）。
default_storage: StorageBackend = LocalDiskStorage(root=settings.MEDIA_ROOT)
