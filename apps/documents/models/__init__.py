"""documents 模型包（规格 §9）：Album 相册、Document 文件元数据。

存储层（ADR-002）与上传服务见 apps.documents.storage / apps.documents.services。
"""

from apps.documents.models.album import ALBUM_CATEGORIES, Album
from apps.documents.models.document import Document

__all__ = ["ALBUM_CATEGORIES", "Album", "Document"]
