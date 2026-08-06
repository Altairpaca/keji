"""seed_demo 管理命令测试（演示数据，规格 §9/§25、ADR-013）。

演示数据约定：
- 客户名以「演示-」前缀；
- 标签名以「演示」开头；
- 其余演示对象（关系/事件/沟通/待办/保单/理赔/文档/相册）经关联的演示客户识别。
- 手机号采用 13900000000+i 假号段模式，无真实 PII。

注意：seed 会真实写 media 文件，本测试把 MEDIA_ROOT 指向 pytest tmp 目录。
"""

import re
from typing import Any

import pytest
from django.core.management import call_command
from django.db.models import Q

from apps.activities.models import CommunicationRecord, WorkEvent
from apps.claims.models import ClaimCase, ClaimMaterial
from apps.core.management.commands.seed_reset import clear_demo_data
from apps.customers.models import Customer, CustomerRelation, Tag
from apps.documents.models import Album, Document
from apps.documents.storage import LocalDiskStorage
from apps.policies.models import Policy
from apps.tasks.models import Task

#: 演示手机号模式：11 位、139 号段（13900000000+i）。
DEMO_PHONE_RE = re.compile(r"^139\d{8}$")

DEMO_CUSTOMER_PREFIX = "演示-"
DEMO_TAG_PREFIX = "演示"


@pytest.fixture
def demo_media(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> LocalDiskStorage:
    """把 default_storage 指向 pytest tmp 目录，避免污染真实 media/。"""
    storage = LocalDiskStorage(tmp_path / "media")
    for module in (
        "apps.documents.storage",
        "apps.documents.services.files",
        "apps.documents.services.thumbnails",
        "apps.core.management.commands.seed_reset",
    ):
        monkeypatch.setattr(f"{module}.default_storage", storage)
    return storage


def _demo_customers() -> Any:
    return Customer.objects.filter(name__startswith=DEMO_CUSTOMER_PREFIX)


def _counts() -> dict[str, int]:
    """各演示实体计数（用于幂等对比）。"""
    customers = _demo_customers()
    return {
        "customers": customers.count(),
        "tags": Tag.objects.filter(name__startswith=DEMO_TAG_PREFIX).count(),
        "relations": CustomerRelation.objects.filter(
            Q(from_customer__in=customers) | Q(to_customer__in=customers)
        ).count(),
        "events": WorkEvent.objects.filter(customer__in=customers).count(),
        "communications": CommunicationRecord.objects.filter(customer__in=customers).count(),
        "tasks": Task.objects.filter(customer__in=customers).count(),
        "albums": Album.objects.filter(
            Q(name__startswith=DEMO_TAG_PREFIX) | Q(customer__in=customers)
        ).count(),
        "documents": Document.objects.filter(customers__in=customers).count(),
        "policies": Policy.objects.filter(
            Q(policyholder__in=customers) | Q(insured__in=customers)
        ).count(),
        "claims": ClaimCase.objects.filter(customer__in=customers).count(),
        "materials": ClaimMaterial.objects.filter(claim__customer__in=customers).count(),
    }


@pytest.mark.django_db
class TestSeedDemo:
    def test_seed_demo_creates_all_entities(
        self, demo_media: LocalDiskStorage, capsys: Any
    ) -> None:
        """seed_demo 后各实体计数 > 0，且 stdout 输出统计。"""
        call_command("seed_demo")

        counts = _counts()
        for key, value in counts.items():
            assert value > 0, f"{key} 应为正数，实际 {value}"

        out = capsys.readouterr().out
        assert "演示数据" in out
        assert "customers" in out

    def test_all_demo_customers_prefixed(self, demo_media: LocalDiskStorage) -> None:
        """所有演示客户 name 以「演示-」前缀。"""
        call_command("seed_demo")
        customers = _demo_customers()
        assert customers.count() >= 12
        assert all(c.name.startswith(DEMO_CUSTOMER_PREFIX) for c in customers)

    def test_demo_phones_not_real_pii(self, demo_media: LocalDiskStorage) -> None:
        """演示手机号全部匹配 139 假号段模式，无真实号段 PII。"""
        call_command("seed_demo")
        for customer in _demo_customers():
            assert customer.phone
            assert DEMO_PHONE_RE.fullmatch(customer.phone), customer.phone

    def test_documents_physical_files_exist(self, demo_media: LocalDiskStorage) -> None:
        """文档物理文件真实存在且可读。"""
        call_command("seed_demo")
        docs = list(Document.objects.filter(customers__in=_demo_customers()))
        assert len(docs) >= 8
        for doc in docs:
            assert demo_media.exists(doc.storage_key), doc.storage_key
            with demo_media.open(doc.storage_key) as fh:
                assert fh.read(8) == b"\x89PNG\r\n\x1a\n"

    def test_seed_repeat_without_reset_does_not_duplicate(
        self, demo_media: LocalDiskStorage
    ) -> None:
        """重复 seed_demo（不带 --reset）不重复建，计数一致。"""
        call_command("seed_demo")
        first = _counts()

        call_command("seed_demo")
        second = _counts()

        assert second == first

    def test_reset_is_idempotent(self, demo_media: LocalDiskStorage) -> None:
        """--reset 后重建的数据规模与首次 seed 一致（幂等）。"""
        call_command("seed_demo")
        first = _counts()

        call_command("seed_demo", "--reset")
        reset = _counts()

        assert reset == first

    def test_reset_clears_then_seed_restores(self, demo_media: LocalDiskStorage) -> None:
        """clear_demo_data 清空后计数归 0；再次 seed 恢复。"""
        call_command("seed_demo")
        assert all(v > 0 for v in _counts().values())

        clear_demo_data()
        cleared = _counts()
        assert all(v == 0 for v in cleared.values()), cleared

        call_command("seed_demo")
        restored = _counts()
        assert all(v > 0 for v in restored.values())

    def test_reset_deletes_physical_files(self, demo_media: LocalDiskStorage) -> None:
        """clear_demo_data 同时清理文档物理文件。"""
        call_command("seed_demo")
        docs = list(Document.objects.filter(customers__in=_demo_customers()))
        assert all(demo_media.exists(d.storage_key) for d in docs)

        clear_demo_data()

        assert all(not demo_media.exists(d.storage_key) for d in docs)
