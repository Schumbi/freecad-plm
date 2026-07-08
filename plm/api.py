import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .auth import api_auth_required
from .models import Annotation, AuditEvent, Checkout, Part, Project, ProjectSnapshot, Revision
from .models import ApiToken
from .permissions import can_upload_revision, is_plm_admin
from .services import (
    cancel_checkout,
    checkin_checkout,
    checkin_checkout_files,
    checkout_manifest,
    create_annotation,
    create_checkout,
    import_project_snapshot,
    next_part_number,
    revision_manifest,
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


@csrf_exempt
@api_auth_required(get=ApiToken.Scope.READ, post=ApiToken.Scope.ADMIN)
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
        status=data.get("status", Project.Status.RUNNING),
        project_date=parse_date(data.get("project_date", "")) or timezone.localdate(),
    )
    AuditEvent.objects.create(
        actor=request.user,
        action=AuditEvent.Action.PROJECT_CREATED,
        object_repr=str(project),
        metadata={"project_id": project.id, "project_code": project.code},
    )
    return JsonResponse({"project": project_payload(project)}, status=201)


@csrf_exempt
@api_auth_required(post=ApiToken.Scope.ADMIN)
@require_http_methods(["POST"])
def project_import_api(request):
    if not is_plm_admin(request.user):
        return JsonResponse({"error": "Keine Berechtigung zum Anlegen von Projekten."}, status=403)

    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        return JsonResponse({"error": "Projekt-ZIP fehlt."}, status=400)

    try:
        with transaction.atomic():
            project = Project.objects.create(
                code=request.POST.get("code", "").strip().upper(),
                name=request.POST.get("name", "").strip(),
                description=request.POST.get("description", "").strip(),
                status=request.POST.get("status", Project.Status.RUNNING),
                project_date=parse_date(request.POST.get("project_date", ""))
                or timezone.localdate(),
            )
            AuditEvent.objects.create(
                actor=request.user,
                action=AuditEvent.Action.PROJECT_CREATED,
                object_repr=str(project),
                metadata={"project_id": project.id, "project_code": project.code},
            )
            snapshot = import_project_snapshot(
                project=project,
                uploaded_zip=uploaded_file,
                created_by=request.user,
                name=request.POST.get("snapshot_name", ""),
            )
    except ValidationError as exc:
        return validation_error_response(exc)

    return JsonResponse(project_import_payload(project, snapshot), status=201)


@csrf_exempt
@api_auth_required(get=ApiToken.Scope.READ, post=ApiToken.Scope.ADMIN)
@require_http_methods(["GET", "POST"])
def project_api(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.method == "GET":
        return JsonResponse({"project": project_payload(project)})

    if not is_plm_admin(request.user):
        return JsonResponse({"error": "Keine Berechtigung zum Bearbeiten von Projekten."}, status=403)
    data = json_body(request)
    if "code" in data:
        project.code = data["code"].strip().upper()
    for field in ("name", "description", "status"):
        if field in data:
            setattr(project, field, data[field].strip())
    if "project_date" in data:
        project.project_date = parse_date(data["project_date"]) or project.project_date
    if "is_archived" in data:
        project.is_archived = bool(data["is_archived"])
    project.save()
    AuditEvent.objects.create(
        actor=request.user,
        action=AuditEvent.Action.PROJECT_UPDATED,
        object_repr=str(project),
        metadata={"project_id": project.id, "project_code": project.code},
    )
    return JsonResponse({"project": project_payload(project)})


@csrf_exempt
@api_auth_required(post=ApiToken.Scope.WRITE)
@require_http_methods(["POST"])
def project_snapshot_import_api(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if not can_upload_revision(request.user):
        return JsonResponse({"error": "Keine Berechtigung zum Importieren von Projektstaenden."}, status=403)

    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        return JsonResponse({"error": "Projekt-ZIP fehlt."}, status=400)

    try:
        snapshot = import_project_snapshot(
            project=project,
            uploaded_zip=uploaded_file,
            created_by=request.user,
            name=request.POST.get("name", ""),
        )
    except ValidationError as exc:
        return validation_error_response(exc)

    return JsonResponse(project_import_payload(project, snapshot), status=201)


@csrf_exempt
@api_auth_required(get=ApiToken.Scope.READ, post=ApiToken.Scope.WRITE)
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
@api_auth_required(get=ApiToken.Scope.READ, post=ApiToken.Scope.WRITE)
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


@api_auth_required(get=ApiToken.Scope.READ)
@require_http_methods(["GET"])
def revision_api(request, revision_id):
    revision = get_object_or_404(Revision.objects.select_related("part"), id=revision_id)
    return JsonResponse({"revision": revision_payload(revision, request)})


@csrf_exempt
@api_auth_required(post=ApiToken.Scope.WRITE)
@require_http_methods(["POST"])
def revision_notes_api(request, revision_id):
    revision = get_object_or_404(Revision.objects.select_related("part"), id=revision_id)
    if not user_can_mutate_models(request.user):
        return JsonResponse({"error": "Keine Berechtigung fuer Revisionsnotizen."}, status=403)
    data = json_body(request)
    revision.notes = data.get("notes", "").strip()
    revision.save(update_fields=["notes", "updated_at"])
    AuditEvent.objects.create(
        actor=request.user,
        action=AuditEvent.Action.REVISION_NOTES_UPDATED,
        object_repr=str(revision),
        metadata={"part_id": revision.part_id, "revision_id": revision.id},
    )
    return JsonResponse({"revision": revision_payload(revision, request)})


@api_auth_required(get=ApiToken.Scope.READ)
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


@api_auth_required(get=ApiToken.Scope.READ)
@require_http_methods(["GET"])
def revision_manifest_api(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "part__project"),
        id=revision_id,
    )
    snapshot = None
    snapshot_id = request.GET.get("snapshot_id")
    if snapshot_id:
        snapshot = get_object_or_404(
            ProjectSnapshot,
            id=snapshot_id,
            project=revision.part.project,
        )
    try:
        manifest = revision_manifest(revision, snapshot=snapshot)
    except ValidationError as exc:
        return validation_error_response(exc, status=409)
    add_manifest_download_urls(manifest, request)
    return JsonResponse({"manifest": manifest})


@csrf_exempt
@api_auth_required(post=ApiToken.Scope.CHECKOUT)
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
            "manifest": add_manifest_download_urls(checkout_manifest(checkout), request),
        },
        status=201,
    )


@api_auth_required(get=ApiToken.Scope.CHECKOUT)
@require_http_methods(["GET"])
def active_checkouts_api(request):
    checkouts = (
        Checkout.objects.select_related(
            "part",
            "part__project",
            "base_revision",
            "snapshot",
        )
        .filter(
            checked_out_by=request.user,
            status=Checkout.Status.ACTIVE,
        )
        .order_by("-updated_at", "-created_at")
    )
    return JsonResponse(
        {"checkouts": [active_checkout_payload(checkout) for checkout in checkouts]}
    )


@api_auth_required(get=ApiToken.Scope.READ)
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
    add_manifest_download_urls(manifest, request)
    return JsonResponse({"checkout": checkout_payload(checkout), "manifest": manifest})


@csrf_exempt
@api_auth_required(post=ApiToken.Scope.CHECKOUT)
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
@api_auth_required(post=ApiToken.Scope.CHECKOUT)
@require_http_methods(["POST"])
def checkout_checkin_api(request, checkout_id):
    checkout = get_object_or_404(Checkout.objects.select_related("part"), id=checkout_id)
    if checkout.checked_out_by_id != request.user.id and not is_plm_admin(request.user):
        return JsonResponse({"error": "Nur der Checkout-Besitzer darf einchecken."}, status=403)
    files_metadata = request.POST.get("files_metadata")
    if files_metadata is not None:
        try:
            parsed_metadata = json.loads(files_metadata)
        except json.JSONDecodeError:
            return JsonResponse({"error": "files_metadata muss gueltiges JSON sein."}, status=400)
        if not isinstance(parsed_metadata, list):
            return JsonResponse({"error": "files_metadata muss eine Liste sein."}, status=400)
        try:
            result = checkin_checkout_files(
                checkout,
                parsed_metadata,
                request.FILES,
                request.user,
                notes=request.POST.get("change_summary", ""),
            )
        except ValidationError as exc:
            return validation_error_response(exc, status=409)
        checkout.refresh_from_db()
        root_revision = result["root_revision"]
        return JsonResponse(
            {
                "checkout": checkout_payload(checkout),
                "revision": (
                    revision_summary_payload(root_revision) if root_revision else None
                ),
                "revisions": [
                    {
                        "path": item["path"],
                        "revision": revision_summary_payload(item["revision"]),
                    }
                    for item in result["revisions"]
                ],
                "ignored_files": result["ignored_files"],
            },
            status=201 if result["revisions"] else 200,
        )

    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        return JsonResponse({"error": "FCStd-Datei fehlt."}, status=400)
    try:
        result = checkin_checkout(
            checkout,
            uploaded_file,
            request.user,
            notes=request.POST.get("change_summary", ""),
        )
    except ValidationError as exc:
        return validation_error_response(exc, status=409)
    checkout.refresh_from_db()
    revision = result["root_revision"]
    return JsonResponse(
        {
            "checkout": checkout_payload(checkout),
            "revision": revision_payload(revision, request) if revision else None,
            "revisions": [
                {
                    "path": item["path"],
                    "revision": revision_summary_payload(item["revision"]),
                }
                for item in result["revisions"]
            ],
            "ignored_files": result["ignored_files"],
        },
        status=201 if result["revisions"] else 200,
    )


@csrf_exempt
@api_auth_required(get=ApiToken.Scope.READ, post=ApiToken.Scope.WRITE)
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
@api_auth_required(post=ApiToken.Scope.WRITE, delete=ApiToken.Scope.WRITE)
@require_http_methods(["POST", "DELETE"])
def annotation_api(request, annotation_id):
    annotation = get_object_or_404(Annotation, id=annotation_id)
    if not user_can_mutate_models(request.user):
        return JsonResponse({"error": "Keine Berechtigung fuer Anmerkungen."}, status=403)
    if request.method == "DELETE":
        metadata = {"annotation_id": annotation.id, "part_id": annotation.part_id}
        object_repr = str(annotation)
        annotation.delete()
        AuditEvent.objects.create(
            actor=request.user,
            action=AuditEvent.Action.ANNOTATION_DELETED,
            object_repr=object_repr,
            metadata=metadata,
        )
        return JsonResponse({}, status=204)

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
