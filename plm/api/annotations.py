from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from ..auth import api_auth_required
from ..models import Annotation, ApiToken, AuditEvent, Part, Revision
from ..services import create_annotation

from .common import (
    annotation_payload,
    json_body,
    user_can_mutate_models,
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
