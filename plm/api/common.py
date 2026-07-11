import json

from django.http import JsonResponse
from django.urls import reverse
from ..permissions import can_upload_revision, is_plm_admin


def json_body(request):
    if not request.body:
        return {}
    return json.loads(request.body.decode("utf-8"))


def validation_error_response(exc, status=400):
    messages = getattr(exc, "messages", None) or [str(exc)]
    return JsonResponse({"error": messages[0], "messages": messages}, status=status)


def project_payload(project):
    return {
        "id": project.id,
        "code": project.code,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "project_date": project.project_date.isoformat(),
        "is_archived": project.is_archived,
    }


def part_payload(part):
    return {
        "id": part.id,
        "project_id": part.project_id,
        "number": part.number,
        "name": part.name,
        "category": part.category,
        "description": part.description,
        "material": part.material,
        "supplier": part.supplier,
        "tags": part.tags,
        "is_archived": part.is_archived,
    }


def revision_payload(revision, request=None):
    payload = {
        "id": revision.id,
        "part_id": revision.part_id,
        "revision_code": revision.revision_code,
        "status": revision.status,
        "original_filename": revision.original_filename,
        "sha256": revision.sha256,
        "size_bytes": revision.size_bytes,
        "notes": revision.notes,
        "extracted_metadata": revision.extracted_metadata,
        "created_at": revision.created_at.isoformat(),
        "released_at": revision.released_at.isoformat() if revision.released_at else None,
    }
    if request is not None:
        payload["download_url"] = request.build_absolute_uri(
            reverse("plm:api_revision_file", args=[revision.id])
        )
    return payload


def annotation_payload(annotation):
    return {
        "id": annotation.id,
        "project_id": annotation.project_id,
        "part_id": annotation.part_id,
        "revision_id": annotation.revision_id,
        "object_name": annotation.object_name,
        "subelement": annotation.subelement,
        "text": annotation.text,
        "status": annotation.status,
        "created_by": annotation.created_by.username,
        "created_at": annotation.created_at.isoformat(),
    }


def checkout_payload(checkout):
    return {
        "id": checkout.id,
        "part_id": checkout.part_id,
        "base_revision_id": checkout.base_revision_id,
        "snapshot_id": checkout.snapshot_id,
        "status": checkout.status,
        "checked_out_by": checkout.checked_out_by.username,
        "workspace_hint": checkout.workspace_hint,
        "completed_revision_id": checkout.completed_revision_id,
        "created_at": checkout.created_at.isoformat(),
        "completed_at": checkout.completed_at.isoformat() if checkout.completed_at else None,
        "canceled_at": checkout.canceled_at.isoformat() if checkout.canceled_at else None,
    }


def revision_summary_payload(revision):
    return {
        "id": revision.id,
        "revision_code": revision.revision_code,
    }


def snapshot_payload(snapshot):
    return {
        "id": snapshot.id,
        "project_id": snapshot.project_id,
        "name": snapshot.name,
        "created_by": snapshot.created_by.username,
        "created_at": snapshot.created_at.isoformat(),
        "entries": [
            {
                "id": entry.id,
                "path": entry.path,
                "revision_id": entry.revision_id,
                "revision_code": entry.revision.revision_code,
                "part_id": entry.revision.part_id,
                "part_number": entry.revision.part.number,
                "part_name": entry.revision.part.name,
                "part_category": entry.revision.part.category,
            }
            for entry in snapshot.entries.select_related("revision", "revision__part").order_by("path")
        ],
    }


def project_import_payload(project, snapshot):
    return {
        "project": project_payload(project),
        "snapshot": snapshot_payload(snapshot),
        "import_summary": getattr(snapshot, "import_summary", {}),
    }


def active_checkout_payload(checkout):
    return {
        "id": checkout.id,
        "status": checkout.status,
        "created_at": checkout.created_at.isoformat(),
        "updated_at": checkout.updated_at.isoformat(),
        "workspace_hint": checkout.workspace_hint,
        "project": {
            "id": checkout.part.project_id,
            "code": checkout.part.project.code,
            "name": checkout.part.project.name,
        },
        "part": {
            "id": checkout.part_id,
            "number": checkout.part.number,
            "name": checkout.part.name,
        },
        "revision": {
            "id": checkout.base_revision_id,
            "revision_code": checkout.base_revision.revision_code,
            "original_filename": checkout.base_revision.original_filename,
        },
        "snapshot": (
            {
                "id": checkout.snapshot_id,
                "name": checkout.snapshot.name,
            }
            if checkout.snapshot_id
            else None
        ),
        "manifest_url": reverse("plm:api_checkout_manifest", args=[checkout.id]),
    }


def add_manifest_download_urls(manifest, request):
    if "revision" in manifest:
        manifest["revision"]["download_url"] = request.build_absolute_uri(
            reverse("plm:api_revision_file", args=[manifest["revision"]["id"]])
        )
    for item in manifest["files"]:
        item["download_url"] = request.build_absolute_uri(
            reverse("plm:api_revision_file", args=[item["revision_id"]])
        )
    return manifest


def user_can_mutate_models(user):
    return can_upload_revision(user) or is_plm_admin(user)
