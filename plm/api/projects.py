from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from ..auth import api_auth_required
from ..models import ApiToken, AuditEvent, Project
from ..permissions import can_upload_revision, is_plm_admin
from ..services import import_project_snapshot

from .common import (
    json_body,
    project_import_payload,
    project_payload,
    validation_error_response,
)


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
