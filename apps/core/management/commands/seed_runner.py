"""seed_demo 生成逻辑（数据定义见 seed_data.py，重置逻辑见 seed_reset.py）。

对外接口：seed_demo_data，供管理命令与测试复用。
"""

import io
import random
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.activities.models import CommunicationRecord, WorkEvent
from apps.activities.services.activities import create_communication, create_work_event
from apps.claims.models import ClaimMaterial
from apps.claims.services.claims import (
    change_claim_status,
    change_material_status,
    create_claim,
    instantiate_template,
)
from apps.core.management.commands.seed_data import (
    ALBUMS,
    CLAIMS,
    COMM_SPECS,
    CUSTOMERS,
    DOCUMENTS,
    EVENT_SPECS,
    POLICIES,
    RELATIONS,
    TASKS,
)
from apps.customers.models import Customer, CustomerStatus, Tag
from apps.customers.services.customers import assign_tags, create_customer
from apps.customers.services.relations import create_relation
from apps.documents.models import Album
from apps.documents.services.albums import create_album
from apps.documents.services.batch import bulk_mark_important
from apps.documents.services.files import save_upload
from apps.policies.models import Policy
from apps.policies.services.policies import change_status, create_policy
from apps.tasks.services.tasks import create_task

DEMO_CUSTOMER_PREFIX = "演示-"
DEMO_TAG_PREFIX = "演示"
DEMO_USERNAME = "demo"


def _demo_user() -> User:
    """取或建一个演示用户（幂等，复用同名用户）。"""
    user: User = User.objects.get_or_create(
        username=DEMO_USERNAME, defaults={"is_superuser": True}
    )[0]
    return user


def _status(name: str) -> CustomerStatus | None:
    status: CustomerStatus | None = CustomerStatus.objects.filter(name=name).first()
    return status


def _make_png(name: str) -> SimpleUploadedFile:
    """生成 400x300 随机颜色 PNG 占位图（无真实图片）。"""
    color = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    image = Image.new("RGB", (400, 300), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def _seed_customers(user: User) -> list[Customer]:
    customers: list[Customer] = []
    for (
        name,
        gender,
        age_note,
        region,
        occupation,
        phone_suffix,
        status_name,
        priority,
        tag_names,
    ) in CUSTOMERS:
        customer = create_customer(
            name=name,
            owner=user,
            created_by=user,
            gender=gender,
            age_note=age_note,
            region=region,
            occupation=occupation,
            phone=f"139{phone_suffix:08d}",
            wechat_nickname=name,
            status=_status(status_name),
            priority=priority,
            first_contact_date=timezone.localdate() - timedelta(days=90),
            last_contact_date=timezone.localdate() - timedelta(days=3),
            notes="虚构演示客户，请勿当真",
        )
        if tag_names:
            assign_tags(customer, tag_names)
        customers.append(customer)
    return customers


def _seed_activities_and_tasks(user: User, customers: list[Customer]) -> int:
    """生成事件 / 沟通 / 待办，返回新增待办数（含联动待办）。"""
    task_count = 0
    for idx, customer in enumerate(customers):
        for event_type, title, days_ago, summary, followup_days in EVENT_SPECS.get(idx, []):
            kwargs: dict[str, Any] = {
                "event_type": event_type,
                "summary": summary,
                "occurred_at": timezone.now() - timedelta(days=days_ago),
            }
            if followup_days is not None:
                kwargs["next_followup_date"] = timezone.localdate() + timedelta(days=followup_days)
            create_work_event(customer=customer, title=title, **kwargs)
            if followup_days is not None:
                task_count += 1
        for channel, days_ago, quick_result, content, followup_days in COMM_SPECS.get(idx, []):
            kwargs = {
                "channel": channel,
                "content": content,
                "occurred_at": timezone.now() - timedelta(days=days_ago),
            }
            if quick_result:
                kwargs["quick_result"] = quick_result
            if followup_days is not None:
                kwargs["next_followup_date"] = timezone.localdate() + timedelta(days=followup_days)
            create_communication(customer=customer, **kwargs)
            if followup_days is not None:
                task_count += 1
    for customer_idx, task_type, title, due_offset, priority in TASKS:
        create_task(
            title=title,
            task_type=task_type,
            customer=customers[customer_idx],
            due_date=timezone.localdate() + timedelta(days=due_offset),
            priority=priority,
            assignee=user,
            created_by=user,
        )
        task_count += 1
    return task_count


def _seed_documents(user: User, customers: list[Customer], albums: list[Album]) -> int:
    """上传随机 PNG 文档并设置重要标记，返回文档数。"""
    important_pks: list[Any] = []
    for filename, customer_idx, album_idx, sensitivity, important in DOCUMENTS:
        doc = save_upload(
            file=_make_png(filename),
            uploaded_by=user,
            title=filename.removesuffix(".png"),
            note="演示文件（Pillow 生成占位图）",
            sensitivity=sensitivity,
            customers=[customers[customer_idx]],
            albums=[albums[album_idx]] if album_idx is not None else None,
            source="seed_demo",
        )
        if important:
            important_pks.append(doc.pk)
    if important_pks:
        bulk_mark_important(important_pks, True)
    return len(DOCUMENTS)


def _seed_policies_and_claims(user: User, customers: list[Customer]) -> int:
    """生成保单与理赔案件，返回理赔案件数。"""
    policies: list[Policy] = []
    for holder, insured, insurer, name, no, itype, premium, freq, status_after in POLICIES:
        policy = create_policy(
            insurer=insurer,
            name=name,
            policy_no=no,
            policyholder=customers[holder],
            insured=customers[insured],
            insurance_type=itype,
            premium_amount=Decimal(premium),
            payment_frequency=freq,
            effective_date=timezone.localdate() - timedelta(days=365),
            owner=user,
            status="active",
        )
        if status_after != "active":
            change_status(policy=policy, new_status=status_after, changed_by=user, note="演示数据")
        policies.append(policy)

    claim_count = 0
    for customer_idx, policy_idx, claim_type, name, status in CLAIMS:
        claim = create_claim(
            name=name,
            customer=customers[customer_idx],
            policy=policies[policy_idx],
            claim_type=claim_type,
            incident_date=timezone.localdate() - timedelta(days=30),
            report_date=timezone.localdate() - timedelta(days=25),
            owner=user,
            description="虚构演示理赔案例",
        )
        materials = instantiate_template(claim=claim)
        if status == "collecting_materials":
            # 部分材料已核对，部分缺料
            for i, material in enumerate(materials):
                if i < 3:
                    _mark_material_checked(user, material)
                elif i < 5:
                    _mark_material_missing(user, material)
        elif status == "closed":
            for material in materials:
                _mark_material_checked(user, material)
        if status != "consultation":
            change_claim_status(claim=claim, new_status=status, changed_by=user)
        claim_count += 1
    return claim_count


def _mark_material_checked(user: User, material: Any) -> None:
    change_material_status(material=material, new_status="submitted", changed_by=user)
    change_material_status(material=material, new_status="checked", changed_by=user)


def _mark_material_missing(user: User, material: Any) -> None:
    change_material_status(material=material, new_status="submitted", changed_by=user)
    change_material_status(material=material, new_status="needs_supplement", changed_by=user)


def seed_demo_data() -> dict[str, int]:
    """生成全部演示数据，返回各实体计数。"""
    user = _demo_user()
    customers = _seed_customers(user)

    relation_count = 0
    for from_idx, to_idx, relation_type in RELATIONS:
        create_relation(
            from_customer=customers[from_idx],
            to_customer=customers[to_idx],
            relation_type=relation_type,
        )
        relation_count += 1

    albums: list[Album] = []
    for name, category in ALBUMS:
        albums.append(create_album(name=name, category=category, created_by=user))

    task_count = _seed_activities_and_tasks(user, customers)
    document_count = _seed_documents(user, customers, albums)
    claim_count = _seed_policies_and_claims(user, customers)

    return {
        "customers": len(customers),
        "tags": Tag.objects.filter(name__startswith=DEMO_TAG_PREFIX).count(),
        "relations": relation_count,
        "albums": len(albums),
        "documents": document_count,
        "tasks": task_count,
        "policies": len(POLICIES),
        "claims": claim_count,
        "materials": ClaimMaterial.objects.filter(claim__customer__in=customers).count(),
        "events": WorkEvent.objects.filter(customer__in=customers).count(),
        "communications": CommunicationRecord.objects.filter(customer__in=customers).count(),
    }
