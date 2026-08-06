"""理赔案件资料 ZIP 打包导出（规格 §12 导出 / §16 不绕过权限 / §10 安全）。

- 稳定可读顺序：必需材料优先，同组按原插入序（created_at）；
- 清单文件 ``00_说明.txt`` 记录案件信息 + 生成时间 + 材料清单；
- 防路径穿越：zip 内所有路径段经 ``_sanitize_filename`` 消毒；
- 权限边界在视图层（``require_permission("can_export_data")``），
  导出数据即权限内可见的案件材料，不绕过权限（§16）。
"""

import io
import re
import zipfile
from datetime import date, datetime
from typing import BinaryIO

from django.utils import timezone

from apps.accounts.models import User
from apps.claims.models import ClaimCase, ClaimMaterial
from apps.documents.storage import default_storage

#: 路径分隔符 / 反斜杠 / 控制字符统一替换为下划线。
_PATH_SEPARATORS = re.compile(r"[\\/]")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f]")
_TRAVERSAL = re.compile(r"\.\.")

_MAX_FILENAME_LEN = 100


def _sanitize_filename(name: str) -> str:
    """清洗文件名：去掉路径分隔符、``..`` 与控制字符，截断 100 字符。

    空值（或清洗后为空）回退为「未命名」，保证 zip 路径段恒安全。
    """
    cleaned = _PATH_SEPARATORS.sub("_", name)
    cleaned = _TRAVERSAL.sub("_", cleaned)
    cleaned = _CONTROL_CHARS.sub("_", cleaned)
    cleaned = cleaned.strip(" ._")[:_MAX_FILENAME_LEN].strip(" ._")
    return cleaned or "未命名"


def _dedupe_path(path: str, used: set[str]) -> str:
    """zip 内路径冲突时追加 ``(N)`` 后缀（首个不挂后缀，第二份起挂）。"""
    if path not in used:
        used.add(path)
        return path
    stem, dot, ext = path.rpartition(".")
    counter = 2
    while True:
        candidate = f"{stem}({counter}){dot}{ext}" if dot else f"{stem}({counter})"
        if candidate not in used:
            used.add(candidate)
            return candidate
        counter += 1


def _material_sort_key(material: ClaimMaterial) -> tuple[bool, datetime]:
    """必需优先（False 排前），同组按 created_at 即原插入序。"""
    return (not material.is_required, material.created_at)


def _build_manifest(claim: ClaimCase, materials: list[ClaimMaterial], now: datetime) -> str:
    """生成清单文本：案件信息 + 生成时间 + 材料清单。"""
    closed_at = (
        claim.closed_at.strftime("%Y-%m-%d %H:%M:%S") if claim.closed_at is not None else "未结案"
    )
    lines = [
        f"案件名称：{claim.name}",
        f"案件类型：{claim.get_claim_type_display()}",
        f"案件状态：{claim.get_status_display()}",
        f"预估金额：{claim.estimated_amount or ''}",
        f"已赔金额：{claim.actual_paid_amount or ''}",
        f"结案时间：{closed_at}",
        f"生成时间：{now.strftime('%Y-%m-%d %H:%M:%S')}",
        "材料清单：",
    ]
    for index, material in enumerate(materials, start=1):
        required = "必需" if material.is_required else "非必需"
        status = material.get_status_display()
        file_name = (
            _sanitize_filename(material.document.original_name)
            if material.document is not None
            else "无文件"
        )
        lines.append(f"{index:02d}. {material.name} [{required}] [{status}] 文件：{file_name}")
    return "\n".join(lines) + "\n"


def build_claim_zip(claim: ClaimCase, *, now: datetime | None = None) -> tuple[bytes, str]:
    """把案件材料打包为内存 zip，返回 ``(zip_bytes, zip_filename)``。

    - 目录结构：``{案件名}/00_说明.txt`` + ``{案件名}/01_材料/{序号:02d}_{材料名}/{原始文件名}``；
    - 无 document 或文件缺失的材料写 ``{序号:02d}_缺失.txt`` 注明；
    - 有 document 但存储层已无文件时同样写缺失说明，不中断导出；
    - ``now`` 供测试注入，默认取当前时间。
    """
    generated_at = now or timezone.now()
    materials = sorted(claim.materials.all(), key=_material_sort_key)
    manifest = _build_manifest(claim, materials, generated_at)

    claim_dir = _sanitize_filename(claim.name)
    buffer = io.BytesIO()
    used_paths: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{claim_dir}/00_说明.txt", manifest)
        for index, material in enumerate(materials, start=1):
            folder = f"{claim_dir}/01_材料/{index:02d}_{_sanitize_filename(material.name)}"
            doc = material.document
            if doc is not None and default_storage.exists(doc.storage_key):
                entry = _dedupe_path(
                    f"{folder}/{_sanitize_filename(doc.original_name)}", used_paths
                )
                archive.writestr(entry, _read_storage_file(doc.storage_key))
            else:
                archive.writestr(
                    f"{claim_dir}/01_材料/{index:02d}_缺失.txt",
                    f"材料「{material.name}」暂无已上传文件。\n",
                )

    zip_filename = f"理赔资料_{claim_dir}_{date.today()}.zip"
    return buffer.getvalue(), zip_filename


def _read_storage_file(storage_key: str) -> bytes:
    """读取存储层文件内容并关闭流（存在性已在调用点经 ``exists`` 校验）。"""
    stream: BinaryIO = default_storage.open(storage_key)
    try:
        return stream.read()
    finally:
        stream.close()


def record_export_audit(*, claim: ClaimCase, user: User | None) -> None:
    """审计接入点：导出理赔 ZIP 记录到 audit（失败不阻断导出）。"""
    try:
        from apps.audit.services import record_audit as _record_audit
    except ImportError:
        return
    _record_audit(
        action="claim_export_zip",
        object_type="claims.ClaimCase",
        object_pk=str(claim.pk),
        target_label=f"理赔案件：{claim.name}",
        actor=user,
    )
