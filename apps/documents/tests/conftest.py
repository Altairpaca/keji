"""documents 测试公共 fixture。"""

from pathlib import Path

import pytest

from apps.documents.storage import LocalDiskStorage


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalDiskStorage:
    """每个测试独立的临时存储后端，替换服务 / 视图中的 default_storage 引用。

    上传服务与下载视图在调用点经 ``模块.default_storage`` 取值，
    monkeypatch 使测试不触碰真实 MEDIA_ROOT。
    """
    backend = LocalDiskStorage(root=tmp_path)
    for module_name in (
        "apps.documents.services.files",
        "apps.documents.services.thumbnails",
        "apps.documents.services.recycle",
        "apps.documents.views",
        "apps.documents.views_viewer",
    ):
        monkeypatch.setattr(f"{module_name}.default_storage", backend)
    return backend
