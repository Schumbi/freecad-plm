from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from ..models import Project, ProjectDocument, ProjectDocumentVersion
from ..permissions import can_upload_revision
from ..services.documents import upload_document


@login_required
def project_documents(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    error = ""
    if request.method == "POST":
        if not can_upload_revision(request.user):
            return HttpResponseForbidden("Keine Berechtigung zum Hochladen.")
        uploaded = request.FILES.get("file")
        if uploaded is None:
            error = "Bitte eine Datei auswählen."
        else:
            try:
                upload_document(project, request.POST.get("path") or uploaded.name, uploaded, request.user)
            except ValidationError as exc:
                error = " ".join(exc.messages)
        if not error:
            messages.success(request, "Projektdatei gespeichert.")
            return redirect("plm:project_documents", project_id=project.pk)
    return render(request, "plm/project_documents.html", {
        "project": project, "documents": project.documents.prefetch_related("versions").order_by("path"),
        "can_manage": can_upload_revision(request.user), "error": error,
    }, status=400 if error else 200)


@login_required
def project_document_state(request, document_id):
    document = get_object_or_404(ProjectDocument, pk=document_id)
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung.")
    if request.method != "POST":
        return redirect("plm:project_documents", project_id=document.project_id)
    action = request.POST.get("action")
    if action in {"archive", "restore"}:
        document.is_archived = action == "archive"
        document.save(update_fields=["is_archived", "updated_at"])
    return redirect("plm:project_documents", project_id=document.project_id)


@login_required
def project_document_download(request, version_id):
    version = get_object_or_404(ProjectDocumentVersion, pk=version_id)
    preview = request.GET.get("preview") == "1" and version.filename.lower().endswith(".pdf")
    response = FileResponse(version.file.open("rb"), as_attachment=not preview,
                            filename=version.filename,
                            content_type="application/pdf" if preview else "application/octet-stream")
    response["X-Content-Type-Options"] = "nosniff"
    return response
