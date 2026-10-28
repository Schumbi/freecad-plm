from django.db.models import Count, Q
from django.db.models.functions import Lower
from ..models import ProjectTag
from ..services.project_tags import filter_projects
from io import BytesIO
from zipfile import ZipFile
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from pathlib import PurePosixPath
from uuid import uuid4
from django.http import FileResponse, HttpResponseForbidden, QueryDict
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from ..derivatives import prepare_revision_derivatives
from ..forms import PrintProjectReassignForm, ProjectForm, ProjectSnapshotUploadForm
from ..models import AuditEvent, Part, PrintProject, PrintProjectPlate, PrintProjectSource, Project, ProjectFolder, ProjectSnapshot, Revision
from ..permissions import can_upload_revision, is_plm_admin
from ..services import delete_project_tree, import_project_snapshot, search_plm
from ..services.snapshots import iter_project_zip_members
from ..services.manufacturing import inspect_manufacturing_upload
from ..services.print_projects import delete_print_project, reassign_print_project


@login_required
def global_search(request):
    query = request.GET.get("q", "").strip()
    project_id = request.GET.get("project", "").strip()
    revision_status = request.GET.get("status", "").strip()
    file_format = request.GET.get("format", "").strip()
    category = request.GET.get("category", "").strip()
    if revision_status not in {value for value, _label in Revision.Status.choices}:
        revision_status = ""
    if file_format not in {value for value, _label in Revision.FileFormat.choices}:
        file_format = ""
    if category not in {value for value, _label in Part.Category.choices}:
        category = ""
    try:
        project_id_value = int(project_id) if project_id else None
    except ValueError:
        project_id_value = None
        project_id = ""
    filters_active = any((project_id_value, revision_status, file_format, category))
    results = (
        search_plm(
            query,
            project_id=project_id_value,
            revision_status=revision_status,
            file_format=file_format,
            category=category,
        )
        if query or filters_active
        else None
    )
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
            "filters_active": filters_active,
            "projects": Project.objects.filter(is_archived=False).order_by("code"),
            "selected_project_id": project_id_value,
            "selected_revision_status": revision_status,
            "selected_file_format": file_format,
            "selected_category": category,
            "revision_status_choices": Revision.Status.choices,
            "file_format_choices": Revision.FileFormat.choices,
            "category_choices": Part.Category.choices,
        },
    )


@login_required
def project_list(request):
    view_choices = [("tiles", "Kacheln"), ("list", "Liste"), ("details", "Details")]
    sort_choices = [("code", "Projektcode"), ("name", "Projektname"),
                    ("created_at", "Erstellungsdatum"), ("updated_at", "Zuletzt geändert"),
                    ("project_date", "Projektdatum")]
    view = request.GET.get("view", "tiles")
    if view not in dict(view_choices):
        view = "tiles"
    sort = request.GET.get("sort", "code")
    if sort not in dict(sort_choices):
        sort = "code"
    direction = "desc" if request.GET.get("direction") == "desc" else "asc"
    ordering = Lower(sort) if sort in {"code", "name"} else sort
    selected_folder = request.GET.get("folder", "all")
    projects = filter_projects(
        Project.objects.filter(is_archived=False).prefetch_related("tags"), request.GET,
    ).annotate(part_count=Count("parts", distinct=True),
               snapshot_count=Count("snapshots", distinct=True))
    if selected_folder == "none":
        projects = projects.filter(folder__isnull=True)
    elif selected_folder != "all":
        projects = projects.filter(folder_id=selected_folder) if selected_folder.isdecimal() and len(selected_folder) <= 18 else projects.none()
    if sort in {"code", "name"}:
        ordering = ordering.desc() if direction == "desc" else ordering.asc()
    elif direction == "desc":
        ordering = "-" + ordering
    projects = projects.order_by(ordering, "pk")
    presentation = QueryDict(mutable=True)
    presentation.update({"view": view, "sort": sort, "direction": direction})
    if selected_folder != "all":
        presentation["folder"] = selected_folder
    tags = list(ProjectTag.objects.annotate(
        project_count=Count("projects", filter=Q(projects__is_archived=False)),
    ))
    selected_tags = request.GET.getlist("tag")
    folders = list(ProjectFolder.objects.order_by("name", "pk"))
    by_id = {folder.pk: folder for folder in folders}
    active_folders = set()
    folder_path = []
    cursor = int(selected_folder) if selected_folder.isdecimal() and len(selected_folder) <= 18 else None
    while cursor in by_id and cursor not in active_folders:
        active_folders.add(cursor)
        folder_path.append(by_id[cursor].name)
        cursor = by_id[cursor].parent_id
    selected_folder_label = (
        "Alle Projekte" if selected_folder == "all" else
        "Ohne Ordner" if selected_folder == "none" else
        " / ".join(reversed(folder_path)) if folder_path else "Ordner auswählen"
    )
    def children(parent_id, ancestors=frozenset()):
        return [{"folder": folder, "children": children(folder.pk, ancestors | {folder.pk})}
                for folder in folders if folder.parent_id == parent_id and folder.pk not in ancestors]
    return render(
        request,
        "plm/project_list.html",
        {
            "projects": projects,
            "folder_tree": children(None),
            "active_folders": active_folders,
            "selected_folder": selected_folder,
            "selected_folder_label": selected_folder_label,
            "project_view": view,
            "view_choices": view_choices,
            "project_sort": sort,
            "sort_choices": sort_choices,
            "project_direction": direction,
            "presentation_query": presentation.urlencode(),
            "can_create_project": is_plm_admin(request.user),
            "tags": tags,
            "selected_tags": selected_tags,
            "selected_tag_names": [tag.name for tag in tags if str(tag.pk) in selected_tags],
            "tags_open": request.GET.get("tag_picker") == "1",
            "query": request.GET.get("q", ""),
            "tag_mode": request.GET.get("mode", "all"),
            "untagged": request.GET.get("untagged") == "1",

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
        .prefetch_related("entries__revision__part", "documents__version")
        .order_by("-created_at")
    )
    print_projects = project.print_projects.select_related("primary_revision__part").prefetch_related("sources", "plates", "snapshots")
    return render(
        request,
        "plm/project_detail.html",
        {
            "project": project,
            "parts": parts,
            "archived_parts": project.parts.filter(is_archived=True).order_by("number") if is_plm_admin(request.user) else [],
            "snapshots": snapshots,
            "print_projects": print_projects,
            "snapshot_form": ProjectSnapshotUploadForm(),
            "can_create_part": can_upload_revision(request.user),
            "can_edit_project": is_plm_admin(request.user),
            "can_delete_print_projects": is_plm_admin(request.user),
        },
    )


@login_required
def delete_print_project_view(request, print_project_id):
    print_project = get_object_or_404(
        PrintProject.objects.select_related(
            "project", "primary_revision", "primary_revision__part"
        ).prefetch_related("sources", "plates", "snapshots"),
        id=print_project_id,
    )
    if not is_plm_admin(request.user):
        return HttpResponseForbidden(
            "Keine Berechtigung zum Loeschen von Druckprojekten."
        )

    project_id = print_project.project_id
    if request.method == "POST":
        code = print_project.code
        try:
            delete_print_project(print_project, request.user)
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
        else:
            messages.success(
                request,
                f"Druckprojekt {code} wurde dauerhaft gelöscht.",
            )
        return redirect("plm:project_detail", project_id=project_id)

    return render(
        request,
        "plm/print_project_confirm_delete.html",
        {
            "print_project": print_project,
            "project": print_project.project,
            "snapshot_count": print_project.snapshots.count(),
        },
    )


@login_required
def upload_print_project_source(request, print_project_id):
    print_project = get_object_or_404(PrintProject, id=print_project_id)
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Hinzufügen von STL-Quellen.")
    if request.method != "POST":
        return redirect("plm:project_detail", project_id=print_project.project_id)

    uploaded = request.FILES.get("file")
    if uploaded is None or not uploaded.name.lower().endswith(".stl"):
        messages.error(request, "Bitte eine STL-Datei auswählen.")
        return redirect("plm:project_detail", project_id=print_project.project_id)
    try:
        info = inspect_manufacturing_upload(uploaded)
    except ValidationError as exc:
        messages.error(request, str(exc))
        return redirect("plm:project_detail", project_id=print_project.project_id)
    source = PrintProjectSource.objects.create(
        print_project=print_project,
        source_type=PrintProjectSource.SourceType.EXTERNAL_STL,
        file=uploaded,
        original_filename=info["original_filename"],
        sha256=info["sha256"],
        size_bytes=info["size_bytes"],
        label=request.POST.get("label", "").strip(),
        uploaded_by=request.user,
    )
    messages.success(request, f"STL-Quelle „{source}“ wurde hinzugefügt.")
    return redirect("plm:project_detail", project_id=print_project.project_id)


@login_required
def download_print_project_slicer(request, print_project_id):
    print_project = get_object_or_404(PrintProject, id=print_project_id)
    if not print_project.slicer_file:
        return HttpResponseForbidden("Noch kein Slicer-Projekt vorhanden.")
    return FileResponse(
        print_project.slicer_file.open("rb"),
        as_attachment=True,
        filename=print_project.slicer_original_filename,
    )


@login_required
def print_project_plate_preview(request, plate_id):
    plate = get_object_or_404(PrintProjectPlate, id=plate_id)
    if not plate.preview:
        return HttpResponseForbidden("Keine Vorschau für diese Druckplatte.")
    return FileResponse(plate.preview.open("rb"), as_attachment=False, filename=plate.preview.name.rsplit("/", 1)[-1])


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

    pending = request.session.get("pending_project_import")
    stage = request.POST.get("stage", "")
    form = ProjectSnapshotUploadForm(request.POST, request.FILES)
    if stage and pending and pending.get("project_id") == project.id:
        storage_name = pending["storage_name"]
        if stage == "cancel":
            default_storage.delete(storage_name)
            request.session.pop("pending_project_import", None)
            return redirect("plm:project_detail", project_id=project.id)
        if not default_storage.exists(storage_name):
            request.session.pop("pending_project_import", None)
            messages.error(request, "Die vorbereitete Importdatei ist nicht mehr vorhanden.")
            return redirect("plm:project_detail", project_id=project.id)
        selected_project = project
        if not pending["fcstd_paths"]:
            selected_project = get_object_or_404(Project, pk=request.POST.get("target_project", project.id), is_archived=False)
            revisions = []
            for part in selected_project.parts.filter(is_archived=False).order_by("number"):
                revision = part.revisions.filter(file_format=Revision.FileFormat.FCSTD).order_by("-created_at", "-id").first()
                if revision:
                    revisions.append(revision)
            if stage == "project" or not request.POST.get("dependency_revision_id"):
                return render(request, "plm/project_import_select.html", {"project": project, "pending": pending, "projects": Project.objects.filter(is_archived=False).order_by("code"), "selected_project": selected_project, "revisions": revisions})
        with default_storage.open(storage_name, "rb") as uploaded:
            uploaded.name = pending["filename"]
            try:
                snapshot = import_project_snapshot(selected_project, uploaded, request.user, name=pending["name"], dependency_root_path=request.POST.get("dependency_root_path", ""), dependency_revision_id=request.POST.get("dependency_revision_id") or None)
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
                return render(request, "plm/project_import_select.html", {"project": project, "pending": pending, "projects": Project.objects.filter(is_archived=False).order_by("code"), "selected_project": selected_project, "revisions": revisions if not pending["fcstd_paths"] else []}, status=400)
        default_storage.delete(storage_name)
        request.session.pop("pending_project_import", None)
    elif form.is_valid():
        uploaded = form.cleaned_data["file"]
        try:
            members = list(iter_project_zip_members(uploaded))
            uploaded.seek(0)
            fcstd_paths = [m.path for m in members if PurePosixPath(m.path).suffix.lower() == ".fcstd"]
            external = [m for m in members if PurePosixPath(m.path).suffix.lower() in {".step", ".stp", ".stl"}]
            if external and len(fcstd_paths) != 1:
                if pending and default_storage.exists(pending.get("storage_name", "")):
                    default_storage.delete(pending["storage_name"])
                storage_name = default_storage.save("pending-imports/" + uuid4().hex + ".zip", uploaded)
                pending = {"storage_name": storage_name, "project_id": project.id, "filename": uploaded.name, "name": form.cleaned_data["name"], "fcstd_paths": fcstd_paths}
                request.session["pending_project_import"] = pending
                return render(request, "plm/project_import_select.html", {"project": project, "pending": pending, "projects": Project.objects.filter(is_archived=False).order_by("code"), "selected_project": project})
            snapshot = import_project_snapshot(project, uploaded, request.user, name=form.cleaned_data["name"])
            selected_project = project
        except ValidationError as exc:
            form.add_error("file", exc)
    else:
        snapshot = None

    if 'snapshot' in locals() and snapshot:
        summary = getattr(snapshot, "import_summary", {})
        derivative_summary = prepare_revision_derivatives([entry.revision for entry in snapshot.entries.select_related("revision")], request.user)
        messages.success(request, f"Projektstand {snapshot.name} wurde importiert: {summary.get('created_revisions', 0)} neue Revisionen, {summary.get('reused_revisions', 0)} unveraenderte Dateien wiederverwendet. {derivative_summary['created_jobs']} Analyse-/PNG-Jobs vorbereitet.")
        return redirect("plm:project_detail", project_id=selected_project.id)

    parts = project.parts.filter(is_archived=False).order_by("number")
    snapshots = (
        project.snapshots.select_related("created_by")
        .prefetch_related("entries__revision__part", "documents__version")
        .order_by("-created_at")
    )
    return render(
        request,
        "plm/project_detail.html",
        {
            "project": project,
            "parts": parts,
            "archived_parts": project.parts.filter(is_archived=True).order_by("number") if is_plm_admin(request.user) else [],
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
        for entry in snapshot.documents.select_related("version").order_by("path"):
            with entry.version.file.open("rb") as fh:
                archive.writestr("Dokumente/" + entry.path, fh.read())
    buffer.seek(0)
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=f"{snapshot.project.code}-{snapshot.name}.zip",
    )


@login_required
def reassign_print_project_view(request, print_project_id):
    item = get_object_or_404(PrintProject.objects.select_related("project", "primary_revision__part"), pk=print_project_id)
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Zuordnen von Druckprojekten.")
    form = PrintProjectReassignForm(request.POST if request.method == "POST" else None, print_project=item)
    if request.method == "POST" and form.is_valid():
        try:
            reassign_print_project(item, form.cleaned_data["revision"], request.user,
                                   expected_revision_id=form.cleaned_data["expected_revision_id"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Druckprojekt {item.code} wurde neu zugeordnet. Der 3MF-Stand bleibt erhalten.")
            revision = form.cleaned_data["revision"]
            return redirect(f"{reverse('plm:part_detail', args=[revision.part_id])}#revision-{revision.id}")
    return render(request, "plm/print_project_reassign.html", {"print_project": item, "form": form})
