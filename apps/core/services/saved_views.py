"""保存视图服务（core）：保存、列表、删除、获取，按 owner 隔离。"""

from typing import Any

from apps.core.models.saved_view import SavedView


def save_view(
    owner: Any,
    name: str,
    app_label: str,
    model_name: str,
    filters: dict[str, Any] | None = None,
    sorts: list[Any] | None = None,
) -> SavedView:
    """保存一个新视图，返回创建的 SavedView。"""
    view = SavedView.objects.create(
        owner=owner,
        name=name,
        app_label=app_label,
        model_name=model_name,
        filters=filters if filters is not None else {},
        sorts=sorts if sorts is not None else [],
    )
    assert isinstance(view, SavedView)
    return view


def list_views(owner: Any, app_label: str, model_name: str) -> list[SavedView]:
    """列出某用户在指定 app/model 下保存的视图，按创建时间倒序。"""
    views: list[SavedView] = []
    for view in SavedView.objects.filter(
        owner=owner, app_label=app_label, model_name=model_name
    ).order_by("-created_at"):
        assert isinstance(view, SavedView)
        views.append(view)
    return views


def delete_view(view: SavedView, owner: Any) -> None:
    """删除视图；非所有者删除时抛 PermissionError。"""
    if view.owner_id != owner.id:
        raise PermissionError("不能删除他人的保存视图")
    view.delete()


def get_view(view_id: Any, owner: Any) -> SavedView:
    """按 id + owner 获取视图；不存在或不属于该 owner 时抛 DoesNotExist。"""
    view = SavedView.objects.get(id=view_id, owner=owner)
    assert isinstance(view, SavedView)
    return view
