from io import BytesIO
from pathlib import PurePosixPath
from uuid import uuid4
from zipfile import ZipFile

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.http import FileResponse
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from .forms import (
    PartForm,
    ProjectForm,
    ProjectSnapshotUploadForm,
    RevisionExportJobForm,
    RevisionNotesForm,
    RevisionUploadForm,
)
from .models import (
    AuditEvent,
    Part,
    Project,
    ProjectSnapshot,
    ProjectSnapshotEntry,
    Revision,
    RevisionArtifact,
    ExportJob,
)
from .permissions import (
    can_edit_revision_notes,
    can_release_revision,
    can_upload_revision,
    is_plm_admin,
)
from .services import (
    PLMRevisionConflict,
    create_revision_from_upload,
    import_project_snapshot,
    next_part_number,
    release_revision,
    revision_reference_files,
    snapshot_entries_with_references,
)
from .freecadcmd import create_export_job, process_export_job, process_queued_export_jobs


PENDING_REVISION_UPLOAD_SESSION_KEY = "pending_revision_upload"


def save_pending_revision_upload(part, uploaded_file, conflict, change_summary=""):
    pending_name = (
        f"pending_uploads/{uuid4().hex}-{PurePosixPath(uploaded_file.name).name}"
    )
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    saved_name = default_storage.save(pending_name, ContentFile(uploaded_file.read()))

    pending = {
        "part_id": part.id,
        "storage_name": saved_name,
        "original_filename": PurePosixPath(uploaded_file.name).name,
        "expected": conflict.expected,
        "actual": conflict.actual,
        "original_sha256": conflict.original_sha256,
        "change_summary": change_summary,
    }
    return pending


def clear_pending_revision_upload(request):
    pending = request.session.pop(PENDING_REVISION_UPLOAD_SESSION_KEY, None)
    request.session.modified = True
    if pending and default_storage.exists(pending["storage_name"]):
        default_storage.delete(pending["storage_name"])
    return pending


def snapshot_entry_for_revision_download(revision):
    if not revision_reference_files(revision):
        return None
    return (
        revision.snapshot_entries.select_related("snapshot", "snapshot__project")
        .order_by("-snapshot__created_at", "path")
        .first()
    )


def referenced_revision_zip_response(root_entry):
    entries = snapshot_entries_with_references(root_entry)
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for entry in entries:
            with entry.revision.file.open("rb") as fh:
                archive.writestr(entry.path, fh.read())
    buffer.seek(0)
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=f"{root_entry.snapshot.project.code}-{PurePosixPath(root_entry.path).stem}-with-references.zip",
    )


@login_required
def project_list(request):
    projects = Project.objects.filter(is_archived=False).order_by("code")
    return render(
        request,
        "plm/project_list.html",
        {
            "projects": projects,
            "can_create_project": is_plm_admin(request.user),
        },
    )


@login_required
def create_project(request):
    if not is_plm_admin(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Anlegen von Projekten.")

    if request.method == "POST":
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save()
            AuditEvent.objects.create(
                actor=request.user,
                action=AuditEvent.Action.PROJECT_CREATED,
                object_repr=str(project),
                metadata={
                    "project_id": project.id,
                    "project_code": project.code,
                },
            )
            messages.success(request, f"Projekt {project.code} wurde angelegt.")
            return redirect("plm:project_detail", project_id=project.id)
    else:
        form = ProjectForm()

    return render(
        request,
        "plm/project_form.html",
        {
            "form": form,
            "title": "Neues Projekt",
            "submit_label": "Anlegen",
            "back_url": "plm:project_list",
        },
        status=400 if request.method == "POST" else 200,
    )


@login_required
def edit_project(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if not is_plm_admin(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Bearbeiten von Projekten.")

    if request.method == "POST":
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            project = form.save()
            AuditEvent.objects.create(
                actor=request.user,
                action=AuditEvent.Action.PROJECT_UPDATED,
                object_repr=str(project),
                metadata={
                    "project_id": project.id,
                    "project_code": project.code,
                    "status": project.status,
                    "project_date": project.project_date.isoformat(),
                },
            )
            messages.success(request, f"Projekt {project.code} wurde gespeichert.")
            return redirect("plm:project_detail", project_id=project.id)
    else:
        form = ProjectForm(instance=project)

    return render(
        request,
        "plm/project_form.html",
        {
            "form": form,
            "project": project,
            "title": f"Eigenschaften: {project.code}",
            "submit_label": "Speichern",
        },
        status=400 if request.method == "POST" else 200,
    )


@login_required
def project_detail(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    parts = project.parts.filter(is_archived=False).order_by("number")
    snapshots = (
        project.snapshots.select_related("created_by")
        .prefetch_related("entries__revision__part")
        .order_by("-created_at")
    )
    return render(
        request,
        "plm/project_detail.html",
        {
            "project": project,
            "parts": parts,
            "snapshots": snapshots,
            "snapshot_form": ProjectSnapshotUploadForm(),
            "can_create_part": can_upload_revision(request.user),
            "can_edit_project": is_plm_admin(request.user),
        },
    )


@login_required
def project_properties(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    return render(
        request,
        "plm/project_properties.html",
        {
            "project": project,
            "can_edit_project": is_plm_admin(request.user),
        },
    )


@login_required
def upload_project_snapshot(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Importieren von Projektstaenden.")
    if request.method != "POST":
        return redirect("plm:project_detail", project_id=project.id)

    form = ProjectSnapshotUploadForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            snapshot = import_project_snapshot(
                project=project,
                uploaded_zip=form.cleaned_data["file"],
                created_by=request.user,
                name=form.cleaned_data["name"],
            )
        except ValidationError as exc:
            form.add_error("file", exc)
        else:
            messages.success(
                request,
                f"Projektstand {snapshot.name} wurde importiert.",
            )
            return redirect("plm:project_detail", project_id=project.id)

    parts = project.parts.filter(is_archived=False).order_by("number")
    snapshots = (
        project.snapshots.select_related("created_by")
        .prefetch_related("entries__revision__part")
        .order_by("-created_at")
    )
    return render(
        request,
        "plm/project_detail.html",
        {
            "project": project,
            "parts": parts,
            "snapshots": snapshots,
            "snapshot_form": form,
            "can_create_part": can_upload_revision(request.user),
        },
        status=400,
    )


@login_required
def create_part(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Anlegen von Teilen.")

    if request.method == "POST":
        form = PartForm(request.POST, request.FILES, project=project)
        if form.is_valid():
            try:
                with transaction.atomic():
                    part = form.save(commit=False)
                    part.project = project
                    if not part.number:
                        part.number = next_part_number(project)
                    part.save()
                    AuditEvent.objects.create(
                        actor=request.user,
                        action=AuditEvent.Action.PART_CREATED,
                        object_repr=str(part),
                        metadata={
                            "project_id": project.id,
                            "part_id": part.id,
                            "part_number": part.number,
                            "category": part.category,
                        },
                    )
                    create_revision_from_upload(
                        part=part,
                        uploaded_file=form.cleaned_data["file"],
                        created_by=request.user,
                        normalize_plm_revision=True,
                        notes=form.cleaned_data.get("change_summary", ""),
                    )
            except ValidationError as exc:
                form.add_error("file", exc)
            else:
                messages.success(
                    request,
                    f"{part.number} wurde mit initialer Revision angelegt.",
                )
                return redirect("plm:part_detail", part_id=part.id)
    else:
        form = PartForm(project=project)

    return render(
        request,
        "plm/part_form.html",
        {
            "project": project,
            "form": form,
        },
        status=400 if request.method == "POST" else 200,
    )


@login_required
def part_detail(request, part_id):
    part = get_object_or_404(Part.objects.select_related("project"), id=part_id)
    revisions = (
        part.revisions.select_related("created_by")
        .prefetch_related("artifacts", "export_jobs")
        .order_by("-created_at")
    )
    selected_revision = None
    selected_revision_id = request.GET.get("properties_revision")
    if selected_revision_id:
        selected_revision = revisions.filter(id=selected_revision_id).first()
    return render(
        request,
        "plm/part_detail.html",
        {
            "part": part,
            "revisions": revisions,
            "selected_revision": selected_revision,
            "form": RevisionUploadForm(),
            "can_upload": can_upload_revision(request.user),
            "can_release": can_release_revision(request.user),
            "can_edit_notes": can_edit_revision_notes(request.user),
            "queued_export_jobs_count": ExportJob.objects.filter(
                status=ExportJob.Status.QUEUED
            ).count(),
        },
    )


@login_required
def part_properties(request, part_id):
    part = get_object_or_404(Part.objects.select_related("project"), id=part_id)
    return render(
        request,
        "plm/part_properties.html",
        {
            "part": part,
        },
    )


@login_required
def revision_properties(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "part__project", "created_by"),
        id=revision_id,
    )
    return render(
        request,
        "plm/revision_properties.html",
        {
            "revision": revision,
        },
    )


@login_required
def process_export_jobs_once(request, part_id):
    part = get_object_or_404(Part, id=part_id)
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Starten von FreeCAD-Jobs.")
    if request.method != "POST":
        return redirect("plm:part_detail", part_id=part.id)

    jobs = process_queued_export_jobs()
    succeeded = sum(1 for job in jobs if job.status == ExportJob.Status.SUCCEEDED)
    failed = sum(1 for job in jobs if job.status == ExportJob.Status.FAILED)
    if jobs:
        messages.success(
            request,
            f"{len(jobs)} Job(s) verarbeitet: {succeeded} erfolgreich, {failed} fehlgeschlagen.",
        )
    else:
        messages.info(request, "Keine wartenden Jobs vorhanden.")
    return redirect("plm:part_detail", part_id=part.id)


@login_required
def upload_revision(request, part_id):
    part = get_object_or_404(Part.objects.select_related("project"), id=part_id)
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Hochladen von Revisionen.")

    if request.method != "POST":
        return redirect("plm:part_detail", part_id=part.id)

    form = RevisionUploadForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            revision = create_revision_from_upload(
                part=part,
                uploaded_file=form.cleaned_data["file"],
                created_by=request.user,
                notes=form.cleaned_data.get("change_summary", ""),
            )
        except PLMRevisionConflict as exc:
            pending = save_pending_revision_upload(
                part,
                form.cleaned_data["file"],
                exc,
                change_summary=form.cleaned_data.get("change_summary", ""),
            )
            request.session[PENDING_REVISION_UPLOAD_SESSION_KEY] = pending
            request.session.modified = True
            return render(
                request,
                "plm/revision_upload_conflict.html",
                {
                    "part": part,
                    "pending": pending,
                },
                status=409,
            )
        except ValidationError as exc:
            form.add_error("file", exc)
        else:
            messages.success(
                request,
                f"Revision {revision.revision_code} wurde hochgeladen.",
            )
            return redirect("plm:part_detail", part_id=part.id)

    revisions = part.revisions.select_related("created_by").order_by("-created_at")
    return render(
        request,
        "plm/part_detail.html",
        {
            "part": part,
            "revisions": revisions,
            "form": form,
            "can_upload": can_upload_revision(request.user),
            "can_release": can_release_revision(request.user),
            "can_edit_notes": can_edit_revision_notes(request.user),
            "queued_export_jobs_count": ExportJob.objects.filter(
                status=ExportJob.Status.QUEUED
            ).count(),
        },
        status=400,
    )


@login_required
def confirm_revision_upload(request, part_id):
    part = get_object_or_404(Part.objects.select_related("project"), id=part_id)
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Hochladen von Revisionen.")
    if request.method != "POST":
        return redirect("plm:part_detail", part_id=part.id)

    pending = request.session.get(PENDING_REVISION_UPLOAD_SESSION_KEY)
    if not pending or pending.get("part_id") != part.id:
        messages.error(request, "Es gibt keinen offenen Revisionsupload.")
        return redirect("plm:part_detail", part_id=part.id)

    action = request.POST.get("action")
    if action == "discard":
        clear_pending_revision_upload(request)
        messages.info(request, "Der Revisionsupload wurde verworfen.")
        return redirect("plm:part_detail", part_id=part.id)

    if action != "normalize":
        messages.error(request, "Unbekannte Upload-Aktion.")
        return redirect("plm:part_detail", part_id=part.id)

    try:
        with default_storage.open(pending["storage_name"], "rb") as source:
            uploaded_file = SimpleUploadedFile(
                pending["original_filename"],
                source.read(),
            )
        revision = create_revision_from_upload(
            part=part,
            uploaded_file=uploaded_file,
            created_by=request.user,
            normalize_plm_revision=True,
            notes=pending.get("change_summary", ""),
        )
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(
            request,
            f"Revision {revision.revision_code} wurde an das PLM angepasst und hochgeladen.",
        )
    finally:
        clear_pending_revision_upload(request)

    return redirect("plm:part_detail", part_id=part.id)


@login_required
def download_revision(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by"),
        id=revision_id,
    )
    snapshot_entry = snapshot_entry_for_revision_download(revision)
    references = revision_reference_files(revision)
    if references and not snapshot_entry:
        return HttpResponseForbidden(
            "Diese FCStd-Datei enthaelt Referenzen und kann nur mit den referenzierten Dateien heruntergeladen werden."
        )
    AuditEvent.objects.create(
        actor=request.user,
        action=AuditEvent.Action.REVISION_DOWNLOADED,
        object_repr=str(revision),
        metadata={
            "part_id": revision.part_id,
            "revision_id": revision.id,
            "revision_code": revision.revision_code,
            "sha256": revision.sha256,
            "original_filename": revision.original_filename,
            "download_mode": "referenced_zip" if snapshot_entry else "single_file",
            "snapshot_entry_id": snapshot_entry.id if snapshot_entry else None,
        },
    )
    if snapshot_entry:
        return referenced_revision_zip_response(snapshot_entry)
    return FileResponse(
        revision.file.open("rb"),
        as_attachment=True,
        filename=revision.original_filename,
    )


@login_required
def release_revision_view(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by"),
        id=revision_id,
    )
    if not can_release_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Freigeben von Revisionen.")
    if request.method != "POST":
        return redirect("plm:part_detail", part_id=revision.part_id)

    try:
        release_revision(revision, request.user)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(
            request,
            f"Revision {revision.revision_code} wurde freigegeben.",
        )
    return redirect("plm:part_detail", part_id=revision.part_id)


@login_required
def update_revision_notes(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by"),
        id=revision_id,
    )
    if not can_edit_revision_notes(request.user):
        return HttpResponseForbidden(
            "Keine Berechtigung zum Bearbeiten von Revisionsnotizen."
        )
    if request.method != "POST":
        return redirect("plm:part_detail", part_id=revision.part_id)

    form = RevisionNotesForm(request.POST, instance=revision)
    if form.is_valid():
        form.save()
        AuditEvent.objects.create(
            actor=request.user,
            action=AuditEvent.Action.REVISION_NOTES_UPDATED,
            object_repr=str(revision),
            metadata={
                "part_id": revision.part_id,
                "revision_id": revision.id,
                "revision_code": revision.revision_code,
            },
        )
        messages.success(
            request,
            f"Anmerkungen fuer Revision {revision.revision_code} wurden gespeichert.",
        )
    return redirect("plm:part_detail", part_id=revision.part_id)


@login_required
def create_revision_inspect_job(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by"),
        id=revision_id,
    )
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Starten von FreeCAD-Jobs.")
    if request.method != "POST":
        return redirect("plm:part_detail", part_id=revision.part_id)

    create_export_job(
        revision=revision,
        job_type=ExportJob.JobType.INSPECT,
        created_by=request.user,
    )
    messages.success(
        request,
        f"FreeCAD-Analyse fuer {revision.revision_code} wurde eingeplant.",
    )
    return redirect("plm:part_detail", part_id=revision.part_id)


@login_required
def create_revision_png_job(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by"),
        id=revision_id,
    )
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Starten von FreeCAD-Jobs.")
    if request.method != "POST":
        return redirect("plm:part_detail", part_id=revision.part_id)

    job = create_export_job(
        revision=revision,
        job_type=ExportJob.JobType.PNG_VIEWS,
        created_by=request.user,
    )
    process_export_job(job)
    job.refresh_from_db()
    if job.status == ExportJob.Status.SUCCEEDED:
        messages.success(
            request,
            f"PNG-Ansichten fuer {revision.revision_code} wurden erzeugt.",
        )
    else:
        messages.error(
            request,
            f"PNG-Ansichten fuer {revision.revision_code} konnten nicht erzeugt werden.",
        )
    return redirect("plm:part_detail", part_id=revision.part_id)


@login_required
def create_revision_export_job(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by"),
        id=revision_id,
    )
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Starten von Exportjobs.")

    if request.method == "POST":
        form = RevisionExportJobForm(request.POST, revision=revision)
        if form.is_valid():
            create_export_job(
                revision=revision,
                job_type=ExportJob.JobType.EXPORT,
                export_format=form.cleaned_data["export_format"],
                selected_objects=form.cleaned_data["selected_objects"],
                created_by=request.user,
            )
            messages.success(
                request,
                f"Exportjob fuer {revision.revision_code} wurde eingeplant.",
            )
            return redirect("plm:part_detail", part_id=revision.part_id)
    else:
        form = RevisionExportJobForm(revision=revision)

    return render(
        request,
        "plm/revision_export_form.html",
        {
            "revision": revision,
            "form": form,
        },
        status=400 if request.method == "POST" else 200,
    )


@login_required
def download_revision_artifact(request, artifact_id):
    artifact = get_object_or_404(
        RevisionArtifact.objects.select_related("revision", "revision__part"),
        id=artifact_id,
    )
    as_attachment = request.GET.get("inline") != "1"
    return FileResponse(
        artifact.file.open("rb"),
        as_attachment=as_attachment,
        filename=artifact.original_filename,
    )


@login_required
def revision_compare(request, part_id):
    part = get_object_or_404(Part.objects.select_related("project"), id=part_id)
    revisions = (
        part.revisions.prefetch_related("artifacts")
        .order_by("-created_at")
    )
    left_id = request.GET.get("left")
    right_id = request.GET.get("right")
    left_revision = revisions.filter(id=left_id).first() if left_id else None
    right_revision = revisions.filter(id=right_id).first() if right_id else None
    comparisons = []
    if left_revision and right_revision:
        left_pngs = {
            artifact.view_name: artifact
            for artifact in left_revision.artifacts.filter(
                artifact_type=RevisionArtifact.ArtifactType.PNG
            )
        }
        right_pngs = {
            artifact.view_name: artifact
            for artifact in right_revision.artifacts.filter(
                artifact_type=RevisionArtifact.ArtifactType.PNG
            )
        }
        for view_name in sorted(set(left_pngs) & set(right_pngs)):
            comparisons.append(
                {
                    "view_name": view_name,
                    "left": left_pngs[view_name],
                    "right": right_pngs[view_name],
                }
            )

    return render(
        request,
        "plm/revision_compare.html",
        {
            "part": part,
            "revisions": revisions,
            "left_revision": left_revision,
            "right_revision": right_revision,
            "comparisons": comparisons,
        },
    )


@login_required
def download_project_snapshot(request, snapshot_id):
    snapshot = get_object_or_404(
        ProjectSnapshot.objects.select_related("project", "created_by"),
        id=snapshot_id,
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for entry in snapshot.entries.select_related("revision").order_by("path"):
            with entry.revision.file.open("rb") as fh:
                archive.writestr(entry.path, fh.read())
    buffer.seek(0)
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=f"{snapshot.project.code}-{snapshot.name}.zip",
    )
