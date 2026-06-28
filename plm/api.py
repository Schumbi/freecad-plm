import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Annotation, AuditEvent, Checkout, Part, Project, ProjectSnapshot, Revision
from .permissions import can_upload_revision, is_plm_admin
from .services import (
    cancel_checkout,
    checkin_checkout,
    checkout_manifest,
    create_annotation,
    create_checkout,
    next_part_number,
)


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


def user_can_mutate_models(user):
    return can_upload_revision(user) or is_plm_admin(user)


@csrf_exempt
@login_required
@require_http_methods(["GET", "POST"])
def projects_api(request):
    if request.method == "GET":
        projects = Project.objects.filter(is_archived=False).order_by("code")
        return JsonResponse({"projects": [project_payload(project) for project in projects]})

    if not is_plm_admin(request.user):
        return JsonResponse({"error": "Keine Berechtigung zum Anlegen von Projekten."}, status=403)
    data = json_body(request)
    project = Project.objects.create(
        code=data.get("code", "").strip().upper(),
        name=data.get("name", "").strip(),
        description=data.get("description", "").strip(),
    )
    AuditEvent.objects.create(
        actor=request.user,
        action=AuditEvent.Action.PROJECT_CREATED,
        object_repr=str(project),
        metadata={"project_id": project.id, "project_code": project.code},
    )
    return JsonResponse({"project": project_payload(project)}, status=201)


@csrf_exempt
@login_required
@require_http_methods(["GET", "POST"])
def project_api(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.method == "GET":
        return JsonResponse({"project": project_payload(project)})

    if not is_plm_admin(request.user):
        return JsonResponse({"error": "Keine Berechtigung zum Bearbeiten von Projekten."}, status=403)
    data = json_body(request)
    for field in ("name", "description"):
        if field in data:
            setattr(project, field, data[field].strip())
    if "is_archived" in data:
        project.is_archived = bool(data["is_archived"])
    project.save()
    return JsonResponse({"project": project_payload(project)})


@csrf_exempt
@login_required
@require_http_methods(["GET", "POST"])
def project_parts_api(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.method == "GET":
        parts = project.parts.filter(is_archived=False).order_by("number")
        return JsonResponse({"parts": [part_payload(part) for part in parts]})

    if not user_can_mutate_models(request.user):
        return JsonResponse({"error": "Keine Berechtigung zum Anlegen von Teilen."}, status=403)
    data = json_body(request)
    number = data.get("number", "").strip() or next_part_number(project)
    part = Part.objects.create(
        project=project,
        number=number,
        name=data.get("name", "").strip() or number,
        category=data.get("category", Part.Category.PART),
        description=data.get("description", "").strip(),
        material=data.get("material", "").strip(),
        supplier=data.get("supplier", "").strip(),
        tags=data.get("tags", "").strip(),
    )
    AuditEvent.objects.create(
        actor=request.user,
        action=AuditEvent.Action.PART_CREATED,
        object_repr=str(part),
        metadata={"project_id": project.id, "part_id": part.id, "part_number": part.number},
    )
    return JsonResponse({"part": part_payload(part)}, status=201)


@csrf_exempt
@login_required
@require_http_methods(["GET", "POST"])
def part_api(request, part_id):
    part = get_object_or_404(Part.objects.select_related("project"), id=part_id)
    if request.method == "GET":
        revisions = part.revisions.order_by("-created_at")
        active_checkout = part.checkouts.filter(status=Checkout.Status.ACTIVE).first()
        return JsonResponse(
            {
                "part": part_payload(part),
                "revisions": [revision_payload(revision, request) for revision in revisions],
                "active_checkout": (
                    checkout_payload(active_checkout) if active_checkout else None
                ),
            }
        )

    if not user_can_mutate_models(request.user):
        return JsonResponse({"error": "Keine Berechtigung zum Bearbeiten von Teilen."}, status=403)
    data = json_body(request)
    for field in ("name", "description", "material", "supplier", "tags", "category"):
        if field in data:
            setattr(part, field, data[field].strip())
    if "is_archived" in data:
        part.is_archived = bool(data["is_archived"])
    part.save()
    return JsonResponse({"part": part_payload(part)})


@login_required
@require_http_methods(["GET"])
def revision_api(request, revision_id):
    revision = get_object_or_404(Revision.objects.select_related("part"), id=revision_id)
    return JsonResponse({"revision": revision_payload(revision, request)})


@login_required
@require_http_methods(["GET"])
def revision_file_api(request, revision_id):
    revision = get_object_or_404(Revision.objects.select_related("part"), id=revision_id)
    AuditEvent.objects.create(
        actor=request.user,
        action=AuditEvent.Action.REVISION_DOWNLOADED,
        object_repr=str(revision),
        metadata={
            "part_id": revision.part_id,
            "revision_id": revision.id,
            "revision_code": revision.revision_code,
            "sha256": revision.sha256,
            "download_mode": "api_file",
        },
    )
    return FileResponse(
        revision.file.open("rb"),
        as_attachment=True,
        filename=revision.original_filename,
    )


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def revision_checkout_api(request, revision_id):
    if not user_can_mutate_models(request.user):
        return JsonResponse({"error": "Keine Berechtigung zum Auschecken."}, status=403)
    revision = get_object_or_404(
        Revision.objects.select_related("part", "part__project"),
        id=revision_id,
    )
    data = json_body(request)
    snapshot = None
    if data.get("snapshot_id"):
        snapshot = get_object_or_404(ProjectSnapshot, id=data["snapshot_id"])
    try:
        checkout = create_checkout(
            base_revision=revision,
            checked_out_by=request.user,
            snapshot=snapshot,
            workspace_hint=data.get("workspace_hint", ""),
        )
    except ValidationError as exc:
        return validation_error_response(exc, status=409)
    return JsonResponse(
        {
            "checkout": checkout_payload(checkout),
            "manifest": checkout_manifest(checkout),
        },
        status=201,
    )


@login_required
@require_http_methods(["GET"])
def checkout_manifest_api(request, checkout_id):
    checkout = get_object_or_404(
        Checkout.objects.select_related(
            "part",
            "part__project",
            "base_revision",
            "snapshot",
            "checked_out_by",
        ),
        id=checkout_id,
    )
    manifest = checkout_manifest(checkout)
    for item in manifest["files"]:
        item["download_url"] = request.build_absolute_uri(
            reverse("plm:api_revision_file", args=[item["revision_id"]])
        )
    return JsonResponse({"checkout": checkout_payload(checkout), "manifest": manifest})


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def checkout_cancel_api(request, checkout_id):
    checkout = get_object_or_404(Checkout, id=checkout_id)
    if checkout.checked_out_by_id != request.user.id and not is_plm_admin(request.user):
        return JsonResponse({"error": "Nur der Checkout-Besitzer darf abbrechen."}, status=403)
    try:
        cancel_checkout(checkout, request.user)
    except ValidationError as exc:
        return validation_error_response(exc, status=409)
    return JsonResponse({"checkout": checkout_payload(checkout)})


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def checkout_checkin_api(request, checkout_id):
    checkout = get_object_or_404(Checkout.objects.select_related("part"), id=checkout_id)
    if checkout.checked_out_by_id != request.user.id and not is_plm_admin(request.user):
        return JsonResponse({"error": "Nur der Checkout-Besitzer darf einchecken."}, status=403)
    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        return JsonResponse({"error": "FCStd-Datei fehlt."}, status=400)
    try:
        revision = checkin_checkout(
            checkout,
            uploaded_file,
            request.user,
            notes=request.POST.get("change_summary", ""),
        )
    except ValidationError as exc:
        return validation_error_response(exc, status=409)
    return JsonResponse(
        {
            "checkout": checkout_payload(checkout),
            "revision": revision_payload(revision, request),
        },
        status=201,
    )


@csrf_exempt
@login_required
@require_http_methods(["GET", "POST"])
def part_annotations_api(request, part_id):
    part = get_object_or_404(Part.objects.select_related("project"), id=part_id)
    if request.method == "GET":
        annotations = part.annotations.select_related("created_by").order_by("-created_at")
        return JsonResponse(
            {"annotations": [annotation_payload(annotation) for annotation in annotations]}
        )

    if not user_can_mutate_models(request.user):
        return JsonResponse({"error": "Keine Berechtigung fuer Anmerkungen."}, status=403)
    data = json_body(request)
    text = data.get("text", "").strip()
    if not text:
        return JsonResponse({"error": "Text darf nicht leer sein."}, status=400)
    revision = None
    if data.get("revision_id"):
        revision = get_object_or_404(Revision, id=data["revision_id"], part=part)
    annotation = create_annotation(
        part=part,
        revision=revision,
        created_by=request.user,
        text=text,
        object_name=data.get("object_name", ""),
        subelement=data.get("subelement", ""),
    )
    return JsonResponse({"annotation": annotation_payload(annotation)}, status=201)


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def annotation_api(request, annotation_id):
    annotation = get_object_or_404(Annotation, id=annotation_id)
    if not user_can_mutate_models(request.user):
        return JsonResponse({"error": "Keine Berechtigung fuer Anmerkungen."}, status=403)
    data = json_body(request)
    if "text" in data:
        annotation.text = data["text"].strip()
    if "status" in data:
        annotation.status = data["status"]
    annotation.save(update_fields=["text", "status", "updated_at"])
    AuditEvent.objects.create(
        actor=request.user,
        action=AuditEvent.Action.ANNOTATION_UPDATED,
        object_repr=str(annotation),
        metadata={"annotation_id": annotation.id, "part_id": annotation.part_id},
    )
    return JsonResponse({"annotation": annotation_payload(annotation)})
