from django.core.exceptions import ValidationError
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..auth import api_auth_required
from ..models import ApiToken, Project, ProjectDocument, ProjectDocumentVersion
from ..permissions import can_upload_revision
from ..services.documents import upload_document
from .common import validation_error_response


def version_payload(version):
    return {"id": version.pk, "number": version.number, "filename": version.filename,
            "sha256": version.sha256, "size": version.size,
            "created_at": version.created_at.isoformat()}


def document_payload(document):
    latest = document.versions.order_by("-number").first()
    return {"id": document.pk, "project_id": document.project_id, "path": document.path,
            "is_archived": document.is_archived,
            "current_version": version_payload(latest) if latest else None}


@csrf_exempt
@api_auth_required(get=ApiToken.Scope.READ, post=ApiToken.Scope.WRITE)
@require_http_methods(["GET", "POST"])
def project_documents_api(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if request.method == "GET":
        return JsonResponse({"documents": [document_payload(d) for d in project.documents.all()]})
    if not can_upload_revision(request.user):
        return JsonResponse({"error": "Keine Berechtigung zum Hochladen."}, status=403)
    uploaded = request.FILES.get("file")
    if uploaded is None:
        return JsonResponse({"error": "Datei fehlt."}, status=400)
    try:
        version, created = upload_document(project, request.POST.get("path") or uploaded.name, uploaded, request.user)
    except ValidationError as exc:
        return validation_error_response(exc)
    return JsonResponse({"document": document_payload(version.document), "version": version_payload(version), "created": created}, status=201 if created else 200)


@csrf_exempt
@api_auth_required(get=ApiToken.Scope.READ, post=ApiToken.Scope.WRITE)
@require_http_methods(["GET", "POST"])
def project_document_api(request, document_id):
    document = get_object_or_404(ProjectDocument, pk=document_id)
    if request.method == "GET":
        result = document_payload(document)
        result["versions"] = [version_payload(v) for v in document.versions.all()]
        return JsonResponse({"document": result})
    if not can_upload_revision(request.user):
        return JsonResponse({"error": "Keine Berechtigung."}, status=403)
    action = request.POST.get("action")
    if action not in {"archive", "restore"}:
        return JsonResponse({"error": "Unbekannte Aktion."}, status=400)
    document.is_archived = action == "archive"
    document.save(update_fields=["is_archived", "updated_at"])
    return JsonResponse({"document": document_payload(document)})


@api_auth_required(get=ApiToken.Scope.READ)
@require_http_methods(["GET"])
def project_document_file_api(request, version_id):
    version = get_object_or_404(ProjectDocumentVersion, pk=version_id)
    preview = request.GET.get("preview") == "1" and version.filename.lower().endswith(".pdf")
    response = FileResponse(version.file.open("rb"), as_attachment=not preview, filename=version.filename,
                            content_type="application/pdf" if preview else "application/octet-stream")
    response["X-Content-Type-Options"] = "nosniff"
    return response
