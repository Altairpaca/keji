"""seed_demo 重置逻辑：删除全部演示数据（含文档物理文件）。"""

from django.db.models import Q

from apps.activities.models import CommunicationRecord, WorkEvent
from apps.claims.models import ClaimCase
from apps.core.management.commands.seed_runner import DEMO_CUSTOMER_PREFIX, DEMO_TAG_PREFIX
from apps.customers.models import Customer, CustomerRelation, Tag
from apps.documents.models import Album, Document
from apps.documents.storage import default_storage
from apps.policies.models import Policy
from apps.tasks.models import Task


def clear_demo_data() -> dict[str, int]:
    """删除全部演示数据（含文档物理文件），返回各实体删除计数。

    顺序：先删引用方（文档/任务/沟通/事件/关系/理赔/保单/相册/标签），
    再删客户；客户最后删，避免外键关联残留。
    """
    customers = Customer.objects.filter(name__startswith=DEMO_CUSTOMER_PREFIX)
    tags = Tag.objects.filter(name__startswith=DEMO_TAG_PREFIX)
    albums = Album.objects.filter(Q(name__startswith=DEMO_TAG_PREFIX) | Q(customer__in=customers))

    documents = Document.objects.filter(Q(customers__in=customers) | Q(albums__in=albums))
    doc_count = documents.count()
    for doc in documents:
        default_storage.delete(doc.storage_key)
        if doc.thumb_storage_key:
            default_storage.delete(doc.thumb_storage_key)
    documents.delete()

    counts = {
        "documents": doc_count,
        "tasks": Task.objects.filter(customer__in=customers).delete()[0],
        "communications": CommunicationRecord.objects.filter(customer__in=customers).delete()[0],
        "events": WorkEvent.objects.filter(customer__in=customers).delete()[0],
        "relations": CustomerRelation.objects.filter(
            Q(from_customer__in=customers) | Q(to_customer__in=customers)
        ).delete()[0],
        "claims": ClaimCase.objects.filter(customer__in=customers).delete()[0],
        "policies": Policy.objects.filter(
            Q(policyholder__in=customers) | Q(insured__in=customers)
        ).delete()[0],
        "albums": albums.delete()[0],
        "tags": tags.delete()[0],
        "customers": customers.delete()[0],
    }
    return counts
