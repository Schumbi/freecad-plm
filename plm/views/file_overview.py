from pathlib import PurePosixPath

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from ..models import (ManufacturingFile, PrintProject, PrintProjectSource,
                      PrintProjectSnapshot, Project, ProjectSnapshot, RevisionArtifact)
from ..services.snapshots import revision_reference_files, resolve_reference_path


def dependency_rows(snapshot):
    if not snapshot:
        return []
    entries = list(snapshot.entries.select_related("revision", "revision__part"))
    by_path = {entry.path: entry for entry in entries}
    by_name = {}
    for entry in entries:
        by_name.setdefault(PurePosixPath(entry.path).name, []).append(entry)
    rows = []
    for entry in entries:
        for reference in revision_reference_files(entry.revision):
            wanted = resolve_reference_path(entry.path, reference)
            exact = by_path.get(wanted)
            matches = [exact] if exact else by_name.get(PurePosixPath(reference).name, [])
            rows.append({"source": entry.path, "target": matches[0].path if len(matches) == 1 else reference,
                         "state": "Eindeutig" if len(matches) == 1 else "Mehrdeutig" if matches else "Fehlt"})
        if entry.dependency_root_path:
            rows.append({"source": entry.dependency_root_path, "target": entry.path,
                         "state": "Eindeutig" if entry.dependency_root_path in by_path else "Fehlt"})
    unique_rows = []
    seen = set()
    for row in rows:
        key = (row["source"], row["target"])
        if key not in seen:
            unique_rows.append(row)
            seen.add(key)
    return unique_rows


@login_required
def project_files_overview(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    snapshots = list(project.snapshots.order_by("-created_at", "-pk"))
    selected_id = request.GET.get("snapshot", "")
    selected = next((s for s in snapshots if str(s.pk) == selected_id), None) if selected_id else (snapshots[0] if snapshots else None)
    compare = next((s for s in snapshots if str(s.pk) == request.GET.get("compare")), None)
    selected_revisions = set(selected.entries.values_list("revision_id", flat=True)) if selected else set()
    selected_documents = set(selected.documents.values_list("version_id", flat=True)) if selected else set()
    rows = []
    for part in project.parts.prefetch_related("revisions"):
        for revision in part.revisions.all():
            rows.append({"name": revision.original_filename, "type": "CAD", "owner": part.number,
                         "version": revision.revision_code, "current": revision == part.revisions.first(),
                         "in_snapshot": revision.pk in selected_revisions,
                         "url": reverse("plm:download_revision", args=[revision.pk])})
    for doc in project.documents.prefetch_related("versions"):
        for version in doc.versions.all():
            rows.append({"name": doc.path, "type": "Dokument", "owner": project.code,
                         "version": f"V{version.number}", "current": version == doc.versions.first() and not doc.is_archived,
                         "in_snapshot": version.pk in selected_documents,
                         "url": reverse("plm:project_document_download", args=[version.pk])})
    for artifact in RevisionArtifact.objects.filter(revision__part__project=project).select_related("revision", "revision__part"):
        rows.append({"name": artifact.original_filename, "type": "Export", "owner": artifact.revision.part.number,
                     "version": artifact.revision.revision_code, "current": True,
                     "in_snapshot": artifact.revision_id in selected_revisions,
                     "url": reverse("plm:download_revision_artifact", args=[artifact.pk])})
    for item in ManufacturingFile.objects.filter(revision__part__project=project).select_related("revision", "revision__part"):
        rows.append({"name": item.original_filename, "type": "Fertigung", "owner": item.revision.part.number,
                     "version": item.revision.revision_code, "current": True,
                     "in_snapshot": item.revision_id in selected_revisions,
                     "url": reverse("plm:download_manufacturing_file", args=[item.pk])})
    for print_project in project.print_projects.all():
        if print_project.slicer_file:
            rows.append({"name": print_project.slicer_original_filename, "type": "Druckprojekt", "owner": print_project.code,
                         "version": "Aktuell", "current": True, "in_snapshot": False,
                         "url": reverse("plm:download_print_project_slicer", args=[print_project.pk])})
        for source in print_project.sources.all():
            if source.file:
                rows.append({"name": source.original_filename, "type": "Druckprojektdatei", "owner": print_project.code,
                             "version": "Quelle", "current": True, "in_snapshot": False,
                             "url": reverse("plm:project_misc_file", args=["source", source.pk])})
        for version in print_project.snapshots.all():
            rows.append({"name": version.original_filename, "type": "Druckprojektdatei", "owner": print_project.code,
                         "version": str(version.pk), "current": False, "in_snapshot": False,
                         "url": reverse("plm:project_misc_file", args=["print-version", version.pk])})
    query = request.GET.get("q", "").casefold().strip()
    if query:
        rows = [r for r in rows if query in (r["name"] + " " + r["type"] + " " + r["owner"]).casefold()]
    if request.GET.get("old") != "1":
        rows = [r for r in rows if r["current"] or r["in_snapshot"]]
    sort_field = request.GET.get("sort", "")
    sort_direction = request.GET.get("direction", "asc")
    if sort_field in {"name", "type", "owner", "version", "in_snapshot"}:
        rows.sort(key=lambda r: str(r[sort_field]).casefold(), reverse=sort_direction == "desc")
    else:
        sort_field = ""
        rows.sort(key=lambda r: (not r["current"], r["type"], r["name"]))
    changed = []
    changed_dependencies = []
    if selected and compare:
        def mapping(snapshot):
            return {e.path: e.revision_id for e in snapshot.entries.all()} | {
                "Dokumente/" + e.path: e.version_id for e in snapshot.documents.all()}
        left, right = mapping(selected), mapping(compare)
        changed = [{"path": path, "state": "Hinzugefügt" if path not in right else "Entfernt" if path not in left else "Geändert"}
                   for path in sorted(left.keys() | right.keys()) if left.get(path) != right.get(path)]
        left_links = {(link["source"], link["target"], link["state"]) for link in dependency_rows(selected)}
        right_links = {(link["source"], link["target"], link["state"]) for link in dependency_rows(compare)}
        changed_dependencies = [{"source": source, "target": target, "state": "Hinzugefügt" if item in left_links else "Entfernt"}
                                for item in sorted(left_links ^ right_links) for source, target, _resolution in [item]]
    links = dependency_rows(selected)
    grouped = {}
    for link in links:
        grouped.setdefault(link["source"], []).append(link)
    return render(request, "plm/project_files_overview.html", {
        "project": project, "snapshots": snapshots, "selected": selected, "compare": compare,
        "rows": rows, "dependencies": links,
        "dependency_tree": [{"source": source, "links": items} for source, items in sorted(grouped.items())],
        "changed": changed,
        "changed_dependencies": changed_dependencies,
        "query": request.GET.get("q", ""), "show_old": request.GET.get("old") == "1",
        "sort_field": sort_field, "sort_direction": sort_direction,
    })


@login_required
def project_misc_file(request, kind, file_id):
    if kind == "source":
        item = get_object_or_404(PrintProjectSource, pk=file_id)
    elif kind == "print-version":
        item = get_object_or_404(PrintProjectSnapshot, pk=file_id)
    else:
        raise Http404
    return FileResponse(item.file.open("rb"), as_attachment=True, filename=item.original_filename)
