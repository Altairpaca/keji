"""T6.1 存储抽象层测试（RED 先行，ADR-002 / docs/security.md 路径穿越防护）。

覆盖：save/open/exists/size/delete 往返、分片存储键格式、原子写（写一半
不残留 .part 临时文件）、路径穿越拒绝（ValueError）、缺键异常、单例。
"""

import io
import re
import uuid
from pathlib import Path

import pytest

from apps.documents.storage import (
    LocalDiskStorage,
    StorageBackend,
    StorageError,
    new_storage_key,
)


@pytest.fixture
def backend(tmp_path: Path) -> LocalDiskStorage:
    return LocalDiskStorage(root=tmp_path)


def test_backend_interface_exposes_required_methods() -> None:
    """ABC 契约：save / open / exists / delete / size 五个方法（ADR-002）。"""
    for method in ("save", "open", "exists", "delete", "size"):
        assert hasattr(StorageBackend, method)


def test_save_open_exists_size_delete_roundtrip(backend: LocalDiskStorage) -> None:
    key = new_storage_key()
    content = b"\xff\xd8\xff\xe0 fake jpeg bytes"

    backend.save(key, io.BytesIO(content))

    assert backend.exists(key) is True
    assert backend.size(key) == len(content)
    assert backend.open(key).read() == content

    backend.delete(key)
    assert backend.exists(key) is False


def test_new_storage_key_is_sharded_uuid() -> None:
    """存储键规范：originals/<uuid4 前 2 位>/<uuid4>（ADR-002/005 分片）。"""
    key = new_storage_key()
    parts = key.split("/")

    assert len(parts) == 3
    assert parts[0] == "originals"
    assert re.fullmatch(r"[0-9a-f]{2}", parts[1])
    uuid.UUID(parts[2])  # 必须是合法 UUID，绝不含文件名 / 客户信息
    assert parts[1] == parts[2][:2]


def test_save_creates_shard_directories(backend: LocalDiskStorage, tmp_path: Path) -> None:
    key = new_storage_key()

    backend.save(key, io.BytesIO(b"x"))

    assert (tmp_path / key).is_file()


class _BrokenStream(io.BytesIO):
    def read(self, size: int | None = -1) -> bytes:
        raise OSError("模拟磁盘写入中断")


def test_save_atomic_no_partial_residue_on_failure(
    backend: LocalDiskStorage, tmp_path: Path
) -> None:
    """写一半抛错：目标路径不残留，分片目录内也无 .part 临时文件。"""
    key = new_storage_key()

    with pytest.raises(OSError):
        backend.save(key, _BrokenStream())

    assert backend.exists(key) is False
    shard_dir = tmp_path / "originals" / key.split("/")[1]
    assert list(shard_dir.iterdir()) == []


@pytest.mark.parametrize(
    "evil",
    [
        "..",
        "../evil",
        "originals/../evil",
        "originals/../../etc/passwd",
        "/etc/passwd",
        "originals//x",
        "originals/ab/..",
        "originals\\ab",
    ],
)
def test_safe_join_rejects_traversal(backend: LocalDiskStorage, evil: str) -> None:
    """含 ``..`` / 绝对路径 / 空段 / 反斜杠的存储键一律 ValueError。"""
    with pytest.raises(ValueError):
        backend.save(evil, io.BytesIO(b"x"))


def test_open_missing_key_raises_storage_error(backend: LocalDiskStorage) -> None:
    with pytest.raises(StorageError):
        backend.open("originals/ab/00000000-0000-0000-0000-000000000000")


def test_size_missing_key_raises_storage_error(backend: LocalDiskStorage) -> None:
    with pytest.raises(StorageError):
        backend.size("originals/ab/00000000-0000-0000-0000-000000000000")


def test_delete_missing_key_is_idempotent(backend: LocalDiskStorage) -> None:
    """对象存储语义：删除不存在的键静默成功（对齐未来 S3Backend）。"""
    backend.delete("originals/ab/00000000-0000-0000-0000-000000000000")


def test_default_storage_is_backend_singleton() -> None:
    from apps.documents.storage import default_storage

    assert isinstance(default_storage, StorageBackend)
