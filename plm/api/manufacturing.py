from django.core.exceptions import ValidationError
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..auth import api_auth_required
from ..models import ApiToken, AuditEvent, ManufacturingFile, Revision
from ..services import sync_slicer_project_from_upload
from .common import (
    manufacturing_file_payload,
    user_can_mutate_models,
    validation_error_response,
)


@csrf_exempt
@api_auth_required(get=ApiToken.Scope.READ, post=ApiToken.Scope.WRITE)
@require_http_methods(["GET", "POST"])
def revision_slicer_project_api(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "part__project"), id=revision_id
    )
    if request.method == "GET":
        project = revision.manufacturing_files.filter(
            file_type=ManufacturingFile.FileType.SLICER_PROJECT_3MF
        ).first()
        return JsonResponse(
            {
                "slicer_project": (
                    manufacturing_file_payload(project, request) if project else None
                )
            }
        )

    if not user_can_mutate_models(request.user):
        return JsonResponse(
            {"error": "Keine Berechtigung fuer Slicer-Projekte."}, status=403
        )
    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        return JsonResponse({"error": "Eine 3MF-Datei ist erforderlich."}, status=400)
    try:
        project, created, changed = sync_slicer_project_from_upload(
            revision=revision,
            uploaded_file=uploaded_file,
            uploaded_by=request.user,
            base_sha256=request.POST.get("base_sha256", ""),
            label=request.POST.get("label", ""),
            slicer_name=request.POST.get("slicer_name", ""),
            slicer_version=request.POST.get("slicer_version", ""),
        )
    except ValidationError as exc:
        status = 409 if "zwischenzeitlich" in str(exc) else 400
        return validation_error_response(exc, status=status)
    return JsonResponse(
        {
            "slicer_project": manufacturing_file_payload(project, request),
            "created": created,
            "changed": changed,
        },
        status=201 if created else 200,
    )


@api_auth_required(get=ApiToken.Scope.READ)
@require_http_methods(["GET"])
def manufacturing_file_api(request, manufacturing_file_id):
    manufacturing_file = get_object_or_404(
        ManufacturingFile.objects.select_related("revision", "revision__part"),
        id=manufacturing_file_id,
    )
    AuditEvent.objects.create(
        actor=request.user,
        action=AuditEvent.Action.MANUFACTURING_FILE_DOWNLOADED,
        object_repr=str(manufacturing_file),
        metadata={
            "manufacturing_file_id": manufacturing_file.id,
            "revision_id": manufacturing_file.revision_id,
            "sha256": manufacturing_file.sha256,
            "download_mode": "api_manufacturing_file",
        },
    )
    return FileResponse(
        manufacturing_file.file.open("rb"),
        as_attachment=True,
        filename=manufacturing_file.original_filename,
    )
