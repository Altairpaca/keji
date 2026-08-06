"""测试通用基础模型：UUID 主键、时间戳、软删除（core）。

基础模型为抽象类，这里用 isolate_apps 定义具体测试模型，
并通过 schema_editor 在测试事务内建表/清表，避免污染全局模型注册表。
"""

import uuid
from collections.abc import Iterator

import pytest
from django.db import connection, models
from django.test.utils import isolate_apps

from apps.core.models.base import SoftDeleteModel, TimeStampedModel, UUIDModel

with isolate_apps("apps.core"):

    class TimestampedItem(TimeStampedModel):
        name = models.CharField(max_length=100)

    class UuidItem(UUIDModel):
        name = models.CharField(max_length=100)

    class SoftDeleteItem(SoftDeleteModel, UUIDModel, TimeStampedModel):
        name = models.CharField(max_length=100)

        class Meta(SoftDeleteModel.Meta, UUIDModel.Meta, TimeStampedModel.Meta):
            abstract = False


@pytest.fixture
def base_model_tables(db: None) -> Iterator[None]:
    """为测试模型建表，测试结束（事务回滚）后清理。"""
    models_list = (TimestampedItem, UuidItem, SoftDeleteItem)
    with connection.schema_editor() as editor:
        for model in models_list:
            editor.create_model(model)
    yield
    with connection.schema_editor() as editor:
        for model in models_list:
            editor.delete_model(model)


@pytest.mark.django_db
def test_uuid_model_generates_uuid_primary_key(base_model_tables: None) -> None:
    item = UuidItem.objects.create(name="a")

    assert isinstance(item.id, uuid.UUID)
    assert item.pk == item.id


@pytest.mark.django_db
def test_timestamped_model_sets_created_and_updated(base_model_tables: None) -> None:
    item = TimestampedItem.objects.create(name="a")

    assert item.created_at is not None
    assert item.updated_at is not None


@pytest.mark.django_db
def test_default_queryset_hides_soft_deleted(base_model_tables: None) -> None:
    item = SoftDeleteItem.objects.create(name="a")
    item.soft_delete()

    assert SoftDeleteItem.objects.count() == 0
    assert SoftDeleteItem.all_objects.count() == 1


@pytest.mark.django_db
def test_soft_delete_sets_flags(base_model_tables: None) -> None:
    item = SoftDeleteItem.objects.create(name="a")
    item.soft_delete()

    deleted = SoftDeleteItem.all_objects.get(pk=item.pk)
    assert deleted.is_deleted is True
    assert deleted.deleted_at is not None


@pytest.mark.django_db
def test_restore_recovers_soft_deleted(base_model_tables: None) -> None:
    item = SoftDeleteItem.objects.create(name="a")
    item.soft_delete()
    item.restore()

    refreshed = SoftDeleteItem.all_objects.get(pk=item.pk)
    assert refreshed.is_deleted is False
    assert refreshed.deleted_at is None
    assert SoftDeleteItem.objects.count() == 1


@pytest.mark.django_db
def test_delete_overridden_to_soft_delete(base_model_tables: None) -> None:
    item = SoftDeleteItem.objects.create(name="a")

    item.delete()

    assert SoftDeleteItem.objects.count() == 0
    assert SoftDeleteItem.all_objects.count() == 1


@pytest.mark.django_db
def test_delete_force_permanently_removes(base_model_tables: None) -> None:
    item = SoftDeleteItem.objects.create(name="a")

    item.delete(force=True)

    assert SoftDeleteItem.all_objects.count() == 0


@pytest.mark.django_db
def test_hard_delete_permanently_removes(base_model_tables: None) -> None:
    item = SoftDeleteItem.objects.create(name="a")

    item.hard_delete()

    assert SoftDeleteItem.all_objects.count() == 0
