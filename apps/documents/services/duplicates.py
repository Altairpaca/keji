"""重复文件服务（T6.3，规格 §9）。

按 SHA-256 分组（objects manager 自动排除软删除），组内未删除文件多于
1 份即为重复组；组内按创建时间倒序排列，去重建议保留最新一份。
"""

from dataclasses import dataclass

from django.db.models import Count

from apps.documents.models import Document


@dataclass(frozen=True)
class DuplicateGroup:
    """一组同 SHA-256 的重复文件。"""

    sha256: str
    count: int
    docs: list[Document]


def find_duplicate_groups() -> list[DuplicateGroup]:
    """返回所有重复组（组内文件数 > 1），按组内数量降序。

    软删除文件不参与分组；组内文档按创建时间倒序（建议保留最新一份）。
    """
    hash_rows = (
        Document.objects.values("sha256")
        .annotate(cnt=Count("id"))
        .filter(cnt__gt=1)
        .order_by("-cnt")
    )
    if not hash_rows:
        return []
    sha_list: list[str] = [row["sha256"] for row in hash_rows]
    docs = Document.objects.filter(sha256__in=sha_list).order_by("sha256", "-created_at")
    grouped: dict[str, list[Document]] = {}
    for doc in docs:
        grouped.setdefault(doc.sha256, []).append(doc)
    counts = {row["sha256"]: row["cnt"] for row in hash_rows}
    return [
        DuplicateGroup(sha256=sha, count=counts[sha], docs=grouped.get(sha, [])) for sha in sha_list
    ]
