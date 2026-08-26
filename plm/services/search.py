from dataclasses import dataclass

from django.db.models import Q

from ..models import Part, Project, ProjectSnapshotEntry, Revision


PLM_SEARCH_RESULT_LIMIT = 50


@dataclass(frozen=True)
class PlmSearchResults:
    projects: list
    parts: list
    revisions: list
    snapshot_paths: list


def search_plm(
    query,
    *,
    project_id=None,
    revision_status="",
    file_format="",
    category="",
    limit=PLM_SEARCH_RESULT_LIMIT,
):
    term = (query or "").strip()
    filters_active = any(
        value for value in (project_id, revision_status, file_format, category)
    )
    if not term and not filters_active:
        return PlmSearchResults(projects=[], parts=[], revisions=[], snapshot_paths=[])

    project_query = Project.objects.filter(is_archived=False)
    part_query = Part.objects.filter(is_archived=False)
    revision_query = Revision.objects.all()
    snapshot_query = ProjectSnapshotEntry.objects.all()

    if project_id:
        project_query = project_query.filter(id=project_id)
        part_query = part_query.filter(project_id=project_id)
        revision_query = revision_query.filter(part__project_id=project_id)
        snapshot_query = snapshot_query.filter(snapshot__project_id=project_id)
    if category:
        project_query = project_query.filter(parts__category=category).distinct()
        part_query = part_query.filter(category=category)
        revision_query = revision_query.filter(part__category=category)
        snapshot_query = snapshot_query.filter(revision__part__category=category)
    if revision_status:
        project_query = project_query.filter(
            parts__revisions__status=revision_status
        ).distinct()
        part_query = part_query.filter(revisions__status=revision_status).distinct()
        revision_query = revision_query.filter(status=revision_status)
        snapshot_query = snapshot_query.filter(revision__status=revision_status)
    if file_format:
        project_query = project_query.filter(
            parts__revisions__file_format=file_format
        ).distinct()
        part_query = part_query.filter(revisions__file_format=file_format).distinct()
        revision_query = revision_query.filter(file_format=file_format)
        snapshot_query = snapshot_query.filter(revision__file_format=file_format)

    if term:
        project_query = project_query.filter(
            Q(code__icontains=term)
            | Q(name__icontains=term)
            | Q(description__icontains=term)
        )
        part_query = part_query.filter(
            Q(number__icontains=term)
            | Q(name__icontains=term)
            | Q(description__icontains=term)
            | Q(project__code__icontains=term)
            | Q(project__name__icontains=term)
        )
        revision_query = revision_query.filter(
            Q(revision_code__icontains=term)
            | Q(original_filename__icontains=term)
            | Q(notes__icontains=term)
            | Q(part__number__icontains=term)
            | Q(part__name__icontains=term)
            | Q(part__project__code__icontains=term)
            | Q(part__project__name__icontains=term)
        )
        snapshot_query = snapshot_query.filter(path__icontains=term)

    projects = list(project_query.order_by("code")[:limit])
    parts = list(
        part_query.select_related("project").order_by("project__code", "number")[:limit]
    )
    revisions = list(
        revision_query
        .select_related("part", "part__project", "created_by")
        .order_by("-created_at")[:limit]
    )
    snapshot_paths = list(
        snapshot_query
        .select_related(
            "snapshot",
            "snapshot__project",
            "revision",
            "revision__part",
            "revision__part__project",
        )
        .order_by("snapshot__project__code", "path")[:limit]
    )
    return PlmSearchResults(
        projects=projects,
        parts=parts,
        revisions=revisions,
        snapshot_paths=snapshot_paths,
    )
