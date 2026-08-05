from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from ..auth import api_auth_required, token_has_scope
from ..models import ApiToken, AuditEvent, Checkout, Part, Project
from ..permissions import is_plm_admin
from ..services import (
    add_checkout_file,
    checkout_manifest,
    create_checkout,
    create_revision_from_upload,
    next_part_number,
)

from .common import (
    add_manifest_download_urls,
    checkout_payload,
    json_body,
    part_payload,
    revision_payload,
    user_can_mutate_models,
    validation_error_response,
)


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
@api_auth_required(post=ApiToken.Scope.WRITE)
@require_http_methods(["POST"])
def create_fcstd_part_api(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if not token_has_scope(request.api_token, ApiToken.Scope.CHECKOUT):
        return JsonResponse(
            {"error": "API-Token hat nicht den benoetigten Checkout-Scope."},
            status=403,
        )
    if not user_can_mutate_models(request.user):
        return JsonResponse(
            {"error": "Keine Berechtigung zum Anlegen von Teilen."},
            status=403,
        )

    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        return JsonResponse(
            {"error": "Eine initiale FCStd-Datei ist erforderlich."},
            status=400,
        )

    category = request.POST.get("category", Part.Category.PART).strip()
    if category not in Part.Category.values:
        return JsonResponse({"error": "Ungueltige Teilekategorie."}, status=400)

    number = request.POST.get("number", "").strip() or next_part_number(project)
    if project.parts.filter(number=number).exists():
        return JsonResponse(
            {"error": "Diese Teilenummer existiert in diesem Projekt bereits."},
            status=409,
        )

    name = request.POST.get("name", "").strip()
    if not name:
        name = PurePosixPath(uploaded_file.name).stem or number

    target_checkout = None
    checkout_id = request.POST.get("checkout_id", "").strip()
    if checkout_id:
        target_checkout = get_object_or_404(
            Checkout.objects.select_related(
                "part",
                "part__project",
                "base_revision",
                "snapshot",
                "checked_out_by",
            ),
            id=checkout_id,
        )
        if (
            target_checkout.checked_out_by_id != request.user.id
            and not is_plm_admin(request.user)
        ):
            return JsonResponse(
                {"error": "Nur der Checkout-Besitzer darf Teile hinzufuegen."},
                status=403,
            )
        if target_checkout.part.project_id != project.id:
            return JsonResponse(
                {"error": "Der aktive Checkout gehoert zu einem anderen Projekt."},
                status=409,
            )

    try:
        with transaction.atomic():
            part = Part.objects.create(
                project=project,
                number=number,
                name=name,
                category=category,
            )
            AuditEvent.objects.create(
                actor=request.user,
                action=AuditEvent.Action.PART_CREATED,
                object_repr=str(part),
                metadata={
                    "project_id": project.id,
                    "part_id": part.id,
                    "part_number": part.number,
                    "category": part.category,
                    "source": "addon_blank_fcstd",
                },
            )
            revision = create_revision_from_upload(
                part=part,
                uploaded_file=uploaded_file,
                created_by=request.user,
                normalize_plm_revision=True,
                notes="Leeres FreeCAD-Modell im Addon angelegt.",
            )

            if target_checkout is not None:
                addition = add_checkout_file(target_checkout, revision, request.user)
                checkout = target_checkout
            else:
                addition = None
                checkout = create_checkout(
                    base_revision=revision,
                    checked_out_by=request.user,
                    workspace_hint=request.POST.get("workspace_hint", ""),
                )

            manifest = add_manifest_download_urls(checkout_manifest(checkout), request)
            added_entry = (
                next(
                    item
                    for item in manifest["files"]
                    if item["path"] == addition.path
                )
                if addition is not None
                else None
            )
    except ValidationError as exc:
        return validation_error_response(exc, status=409)

    payload = {
        "part": part_payload(part),
        "revision": revision_payload(revision, request),
        "checkout": checkout_payload(checkout),
        "manifest": manifest,
    }
    if added_entry is not None:
        payload["added_file"] = added_entry
    return JsonResponse(payload, status=201)


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
