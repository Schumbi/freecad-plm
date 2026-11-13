from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.db import transaction
from django.db.models.deletion import ProtectedError
from pathlib import PurePosixPath

from ..models import Project, ProjectDocument, ProjectDocumentFolder, ProjectDocumentVersion
from ..permissions import can_upload_revision, is_plm_admin
from ..services.documents import upload_document, clean_document_path


@login_required
def project_documents(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    error = ""
    if request.method == "POST":
        if not can_upload_revision(request.user):
            return HttpResponseForbidden("Keine Berechtigung zum Hochladen.")
        action = request.POST.get("action", "upload")
        if action in {"create_folder", "delete_folder"}:
            try:
                folder = clean_document_path(request.POST.get("folder", "").strip())
                if action == "create_folder":
                    ProjectDocumentFolder.objects.get_or_create(project=project, path=folder)
                else:
                    if not is_plm_admin(request.user):
                        return HttpResponseForbidden("Keine Berechtigung zum Löschen.")
                    if project.documents.filter(path__startswith=folder + "/").exists() or project.document_folders.filter(path__startswith=folder + "/").exists():
                        raise ValidationError("Nur leere Ordner können gelöscht werden.")
                    ProjectDocumentFolder.objects.filter(project=project, path=folder).delete()
                return redirect("plm:project_documents", project_id=project.pk)
            except ValidationError as exc:
                error = " ".join(exc.messages)
        uploads = request.FILES.getlist("files") or request.FILES.getlist("file")
        if action in {"create_folder", "delete_folder"}:
            pass
        elif not uploads:
            error = "Bitte eine Datei auswählen."
        else:
            try:
                raw_folder = request.POST.get("folder", "").strip()
                if raw_folder.startswith(("/", "\\")):
                    raise ValidationError("Der Zielordner muss relativ sein.")
                folder = raw_folder.rstrip("/")
                paths = [clean_document_path(f"{folder}/{uploaded.name}" if folder else uploaded.name)
                         for uploaded in uploads]
                if len(paths) != len(set(paths)):
                    raise ValidationError("Dateinamen dürfen im Zielordner nicht doppelt vorkommen.")
                with transaction.atomic():
                    for path, uploaded in zip(paths, uploads):
                        upload_document(project, path, uploaded, request.user, request.POST.get("note", ""))
            except ValidationError as exc:
                error = " ".join(exc.messages)
        if not error:
            messages.success(request, f"{len(uploads)} Projektdatei(en) gespeichert.")
            return redirect("plm:project_documents", project_id=project.pk)
    documents = list(project.documents.prefetch_related("versions").order_by("path"))
    groups = {path: [] for path in project.document_folders.values_list("path", flat=True)}
    for document in documents:
        folder = str(PurePosixPath(document.path).parent)
        groups.setdefault("" if folder == "." else folder, []).append(document)
    return render(request, "plm/project_documents.html", {
        "project": project, "document_groups": sorted(groups.items()),
        "can_manage": can_upload_revision(request.user), "can_delete": is_plm_admin(request.user),
        "folders": sorted(folder for folder in groups if folder),
        "explicit_folders": set(project.document_folders.values_list("path", flat=True)), "error": error,
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
    elif action == "move":
        try:
            folder = request.POST.get("folder", "").strip()
            if folder:
                folder = clean_document_path(folder)
                if not (document.project.document_folders.filter(path=folder).exists() or document.project.documents.filter(path__startswith=folder + "/").exists()):
                    raise ValidationError("Zielordner nicht gefunden.")
            path = clean_document_path(f"{folder}/{PurePosixPath(document.path).name}" if folder else PurePosixPath(document.path).name)
            if document.project.documents.filter(path=path).exclude(pk=document.pk).exists():
                raise ValidationError("Im Zielordner gibt es bereits eine Datei mit diesem Namen.")
            document.path = path
            document.save(update_fields=["path", "updated_at"])
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    elif action == "note":
        version = get_object_or_404(document.versions, pk=request.POST.get("version_id"))
        note = request.POST.get("note", "").strip()
        if len(note) > 255:
            messages.error(request, "Die Anmerkung darf höchstens 255 Zeichen lang sein.")
        else:
            version.note = note
            version.save(update_fields=["note"])
    elif action == "delete":
        if not is_plm_admin(request.user):
            return HttpResponseForbidden("Keine Berechtigung zum Löschen.")
        try:
            with transaction.atomic():
                document = ProjectDocument.objects.select_for_update().get(pk=document.pk)
                files = {(v.file.storage, v.file.name) for v in document.versions.all() if v.file}
                document.delete()
                transaction.on_commit(lambda: [storage.delete(name) for storage, name in files if not ProjectDocumentVersion.objects.filter(file=name).exists()])
            messages.success(request, "Projektdatei und ihre Versionen wurden gelöscht.")
        except ProtectedError:
            messages.error(request, "Die Datei wird in einem Projekt-Snapshot verwendet und kann nicht gelöscht werden. Sie kann archiviert werden.")
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
