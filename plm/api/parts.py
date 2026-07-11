from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from ..auth import api_auth_required
from ..models import ApiToken, AuditEvent, Checkout, Part, Project
from ..services import next_part_number

from .common import (
    checkout_payload,
    json_body,
    part_payload,
    revision_payload,
    user_can_mutate_models,
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
