from django.core.exceptions import ValidationError
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from ..auth import api_auth_required
from ..models import ApiToken, AuditEvent, ProjectSnapshot, Revision
from ..services import revision_manifest

from .common import (
    add_manifest_download_urls,
    json_body,
    revision_payload,
    user_can_mutate_models,
    validation_error_response,
)


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
