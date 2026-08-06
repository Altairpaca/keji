"""claims 服务层：理赔材料 ↔ 文档关联（T8.4，规格 §12 材料项关联文件 / §9 一文件多关联）。

材料的 ``document`` FK 指向 documents.Document，同一文件可被多个材料引用
（规格 §9 一文件多关联）；上传复用 documents.save_upload（校验 / SHA-256 去重 /
缩略图），此处仅叠加材料关联、来源标记与案件客户归属。
"""

from typing import BinaryIO

from django.db import transaction

from apps.accounts.models import User
from apps.claims.models import ClaimMaterial
from apps.documents.models import Document
from apps.documents.services.files import save_upload


def attach_document_to_material(*, material: ClaimMaterial, document: Document) -> ClaimMaterial:
    """关联文档到材料；已关联同一文档时幂等跳过。"""
    if material.document_id == document.pk:
        return material
    material.document = document
    material.save(update_fields=["document", "updated_at"])
    return material


def detach_document_from_material(material: ClaimMaterial) -> ClaimMaterial:
    """解除材料与文档的关联（document 置空）。"""
    material.document = None
    material.save(update_fields=["document", "updated_at"])
    return material


def upload_material_document(
    *, material: ClaimMaterial, file: BinaryIO, uploaded_by: User
) -> tuple[ClaimMaterial, Document]:
    """上传材料文件并关联：事务内 ``save_upload`` → ``attach``。

    - ``customers``：材料所属案件的客户（有则关联，规格 §9 一文件多客户）；
    - ``source``：``claim:<案件pk>``，便于按案件追溯文件来源；
    - ``title``：取材料名，便于在文档列表识别；
    - 重复文件：``DuplicateDocumentError`` 原样上抛，由视图提示「文件已存在」。
    """
    customer = material.claim.customer
    customers = [customer] if customer is not None else None
    with transaction.atomic():
        document = save_upload(
            file=file,
            uploaded_by=uploaded_by,
            title=material.name,
            source=f"claim:{material.claim.pk}",
            customers=customers,
        )
        attach_document_to_material(material=material, document=document)
    return material, document
