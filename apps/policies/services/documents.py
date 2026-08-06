"""policies-文档关联服务（T7.4，规格 §11 关联文件 / §9 一文件多关联）。

一份文件可关联多个保单、一个保单可挂多份文件（双向 M2M）。关系写操作
（attach / detach）经本模块进出，视图不直接操作 M2M。

``policy_documents`` 显式过滤 ``is_deleted=False``：M2M 反向管理器使用
基管理器（不含软删除过滤），直接 ``policy.documents.all()`` 会把回收站
文件也带出来，必须在此收敛。
"""

from django.db.models import QuerySet

from apps.documents.models import Document
from apps.policies.models import Policy


def attach_document_to_policy(policy: Policy, document: Document) -> Document:
    """把文档关联到保单（幂等：重复调用不产生重复关联）。"""
    document.policies.add(policy)
    return document


def detach_document_from_policy(policy: Policy, document: Document) -> Document:
    """解除文档与保单的关联（未关联时静默无操作）。"""
    document.policies.remove(policy)
    return document


def policy_documents(policy: Policy) -> QuerySet[Document]:
    """返回保单名下未删除的关联文档，按上传时间倒序。"""
    return policy.documents.filter(is_deleted=False)
