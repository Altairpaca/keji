"""权限矩阵测试共享 fixtures（apps/core/tests，仅本目录矩阵测试使用）。"""

import uuid

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.claims.models import ClaimCase
from apps.customers.models import Customer, Tag
from apps.documents.models import Document
from apps.policies.models import Policy
from apps.tasks.models import Task


@pytest.fixture
def admin_user() -> User:
    u = User(username="matrix-admin", is_superuser=True, is_staff=True)
    u.save()
    assert isinstance(u, User)
    return u


@pytest.fixture
def plain_user() -> User:
    u = User(username="matrix-plain")
    u.save()
    assert isinstance(u, User)
    return u


@pytest.fixture
def target_user() -> User:
    u = User(username="matrix-target")
    u.save()
    assert isinstance(u, User)
    return u


@pytest.fixture
def customer() -> Customer:
    obj = Customer.objects.create(name="矩阵测试客户")
    assert isinstance(obj, Customer)
    return obj


@pytest.fixture
def tag() -> Tag:
    obj = Tag.objects.create(name="矩阵标签")
    assert isinstance(obj, Tag)
    return obj


@pytest.fixture
def policy(customer: Customer) -> Policy:
    obj = Policy.objects.create(
        insurer="测试保司", name="测试保单", policy_no="POL-MTX-001", policyholder=customer
    )
    assert isinstance(obj, Policy)
    return obj


@pytest.fixture
def claim(customer: Customer) -> ClaimCase:
    obj = ClaimCase.objects.create(name="测试案件", customer=customer)
    assert isinstance(obj, ClaimCase)
    return obj


@pytest.fixture
def task(customer: Customer) -> Task:
    obj = Task.objects.create(title="测试待办", customer=customer, due_date=timezone.localdate())
    assert isinstance(obj, Task)
    return obj


@pytest.fixture
def document() -> Document:
    obj = Document.objects.create(
        original_name="matrix.txt",
        storage_key=f"matrix/{uuid.uuid4()}.txt",
        mime_type="text/plain",
        size=10,
    )
    assert isinstance(obj, Document)
    return obj


@pytest.fixture
def delete_customer() -> Customer:
    """独立客户实例：admin 删除用例专用，避免影响后续复用 customer 的用例。"""
    obj = Customer.objects.create(name="待删除客户")
    assert isinstance(obj, Customer)
    return obj


@pytest.fixture
def trashed_document() -> Document:
    doc = Document.objects.create(
        original_name="trashed.txt",
        storage_key=f"matrix/{uuid.uuid4()}.txt",
        mime_type="text/plain",
        size=10,
    )
    assert isinstance(doc, Document)
    doc.soft_delete()
    return doc
