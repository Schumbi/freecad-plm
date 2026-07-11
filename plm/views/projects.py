from io import BytesIO
from zipfile import ZipFile
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from ..derivatives import prepare_revision_derivatives
from ..forms import ProjectForm, ProjectSnapshotUploadForm
from ..models import AuditEvent, Project, ProjectSnapshot
from ..permissions import can_upload_revision, is_plm_admin
from ..services import delete_project_tree, import_project_snapshot, search_plm


@login_required
def global_search(request):
    query = request.GET.get("q", "").strip()
    results = search_plm(query) if query else None
    total_hits = 0
    if results is not None:
        total_hits = (
            len(results.projects)
            + len(results.parts)
            + len(results.revisions)
            + len(results.snapshot_paths)
        )
    return render(
        request,
        "plm/search.html",
        {
            "query": query,
            "results": results,
            "total_hits": total_hits,
        },
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
def delete_project(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if not is_plm_admin(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Loeschen von Projekten.")

    if request.method == "POST":
        confirmation = request.POST.get("confirmation", "").strip()
        if confirmation == project.code:
            project_code = project.code
            summary = delete_project_tree(project, request.user)
            messages.success(
                request,
                (
                    f"Projekt {project_code} wurde geloescht "
                    f"({summary['parts']} Teile, {summary['revisions']} Revisionen)."
                ),
            )
            return redirect("plm:project_list")
        messages.error(request, "Der eingegebene Projektcode stimmt nicht.")

    return render(
        request,
        "plm/project_confirm_delete.html",
        {"project": project},
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
            summary = getattr(snapshot, "import_summary", {})
            created_revisions = summary.get("created_revisions", 0)
            reused_revisions = summary.get("reused_revisions", 0)
            derivative_summary = prepare_revision_derivatives(
                [entry.revision for entry in snapshot.entries.select_related("revision")],
                request.user,
            )
            message = (
                f"Projektstand {snapshot.name} wurde importiert: "
                f"{created_revisions} neue Revisionen, "
                f"{reused_revisions} unveraenderte Dateien wiederverwendet. "
                f"{derivative_summary['created_jobs']} Analyse-/PNG-Jobs vorbereitet."
            )
            if created_revisions:
                messages.success(request, message)
            else:
                messages.warning(request, message)
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
