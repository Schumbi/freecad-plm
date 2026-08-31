from django.core.exceptions import ValidationError
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..auth import api_auth_required
from ..models import ApiToken, PrintProject, PrintProjectSource, Revision
from ..services.manufacturing import inspect_manufacturing_upload
from .common import json_body, user_can_mutate_models


def payload(item, request=None):
    result = {
        "id": item.id, "project_id": item.project_id, "primary_revision_id": item.primary_revision_id,
        "code": item.code, "name": item.name, "description": item.description,
        "slicer_project": {
            "original_filename": item.slicer_original_filename,
            "sha256": item.slicer_sha256, "size_bytes": item.slicer_size_bytes,
            "metadata": item.slicer_metadata,
        } if item.slicer_file else None,
        "sources": [
            {"id": source.id, "type": source.source_type, "revision_id": source.revision_id,
             "label": source.label, "original_filename": source.original_filename,
             "sha256": source.sha256, "size_bytes": source.size_bytes}
            for source in item.sources.select_related("revision").order_by("id")
        ],
        "snapshots": [
            {"id": snapshot.id, "sha256": snapshot.sha256, "original_filename": snapshot.original_filename,
             "bambuddy_archive_id": snapshot.bambuddy_archive_id, "created_at": snapshot.created_at.isoformat()}
            for snapshot in item.snapshots.all()[:20]
        ],
    }
    if request and item.slicer_file:
        result["slicer_project"]["download_url"] = request.build_absolute_uri(
            f"/api/print-projects/{item.id}/slicer-project/file/"
        )
    return result


@csrf_exempt
@api_auth_required(get=ApiToken.Scope.READ, post=ApiToken.Scope.WRITE)
@require_http_methods(["GET", "POST"])
def print_projects_api(request):
    if request.method == "GET":
        projects = PrintProject.objects.select_related("project", "primary_revision").prefetch_related("sources", "snapshots")
        return JsonResponse({"print_projects": [payload(item, request) for item in projects]})
    if not user_can_mutate_models(request.user):
        return JsonResponse({"error": "Keine Berechtigung für Druckprojekte."}, status=403)
    data = json_body(request)
    revision = get_object_or_404(Revision.objects.select_related("part__project"), id=data.get("revision_id"))
    code = str(data.get("code", "")).strip()
    name = str(data.get("name", "")).strip()
    if not code or not name:
        return JsonResponse({"error": "Code und Name sind erforderlich."}, status=400)
    item, created = PrintProject.objects.get_or_create(
        project=revision.part.project, code=code,
        defaults={"primary_revision": revision, "name": name, "description": str(data.get("description", "")).strip()},
    )
    if item.primary_revision_id != revision.id:
        return JsonResponse({"error": "Der Druckprojekt-Code ist bereits einer anderen Revision zugeordnet."}, status=409)
    PrintProjectSource.objects.get_or_create(
        print_project=item, revision=revision, source_type=PrintProjectSource.SourceType.REVISION,
        defaults={"uploaded_by": request.user, "label": f"{revision.part.number} {revision.revision_code}"},
    )
    return JsonResponse({"print_project": payload(item, request), "created": created}, status=201 if created else 200)


@csrf_exempt
@api_auth_required(get=ApiToken.Scope.READ, post=ApiToken.Scope.WRITE)
@require_http_methods(["GET", "POST"])
def print_project_slicer_api(request, print_project_id):
    item = get_object_or_404(PrintProject.objects.prefetch_related("sources", "snapshots"), id=print_project_id)
    if request.method == "GET":
        return JsonResponse({"print_project": payload(item, request)})
    if not user_can_mutate_models(request.user):
        return JsonResponse({"error": "Keine Berechtigung für Druckprojekte."}, status=403)
    uploaded = request.FILES.get("file")
    if uploaded is None:
        return JsonResponse({"error": "Eine 3MF-Datei ist erforderlich."}, status=400)
    try:
        info = inspect_manufacturing_upload(uploaded)
    except ValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    if not info["original_filename"].lower().endswith(".3mf"):
        return JsonResponse({"error": "Ein Druckprojekt benötigt eine 3MF-Datei."}, status=400)
    item.slicer_file = uploaded
    item.slicer_original_filename = info["original_filename"]
    item.slicer_sha256 = info["sha256"]
    item.slicer_size_bytes = info["size_bytes"]
    item.slicer_metadata = info["metadata"]
    item.slicer_updated_by = request.user
    item.save()
    return JsonResponse({"print_project": payload(item, request)})


@csrf_exempt
@api_auth_required(post=ApiToken.Scope.WRITE)
@require_http_methods(["POST"])
def print_project_source_api(request, print_project_id):
    item = get_object_or_404(PrintProject, id=print_project_id)
    if not user_can_mutate_models(request.user):
        return JsonResponse({"error": "Keine Berechtigung für Druckprojekte."}, status=403)
    uploaded = request.FILES.get("file")
    if uploaded is None or not uploaded.name.lower().endswith(".stl"):
        return JsonResponse({"error": "Eine STL-Datei ist erforderlich."}, status=400)
    info = inspect_manufacturing_upload(uploaded)
    source = PrintProjectSource.objects.create(
        print_project=item, source_type=PrintProjectSource.SourceType.EXTERNAL_STL,
        file=uploaded, original_filename=info["original_filename"], sha256=info["sha256"],
        size_bytes=info["size_bytes"], label=request.POST.get("label", "").strip(), uploaded_by=request.user,
    )
    return JsonResponse({"source_id": source.id}, status=201)


@api_auth_required(get=ApiToken.Scope.READ)
@require_http_methods(["GET"])
def print_project_slicer_file_api(request, print_project_id):
    item = get_object_or_404(PrintProject, id=print_project_id)
    if not item.slicer_file:
        return JsonResponse({"error": "Noch kein Slicer-Projekt vorhanden."}, status=404)
    return FileResponse(item.slicer_file.open("rb"), as_attachment=True, filename=item.slicer_original_filename)
