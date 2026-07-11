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


def search_plm(query, *, limit=PLM_SEARCH_RESULT_LIMIT):
    term = (query or "").strip()
    if not term:
        return PlmSearchResults(projects=[], parts=[], revisions=[], snapshot_paths=[])

    projects = list(
        Project.objects.filter(is_archived=False)
        .filter(
            Q(code__icontains=term)
            | Q(name__icontains=term)
            | Q(description__icontains=term)
        )
        .order_by("code")[:limit]
    )
    parts = list(
        Part.objects.filter(is_archived=False)
        .filter(
            Q(number__icontains=term)
            | Q(name__icontains=term)
            | Q(description__icontains=term)
            | Q(project__code__icontains=term)
            | Q(project__name__icontains=term)
        )
        .select_related("project")
        .order_by("project__code", "number")[:limit]
    )
    revisions = list(
        Revision.objects.filter(
            Q(revision_code__icontains=term)
            | Q(original_filename__icontains=term)
            | Q(notes__icontains=term)
            | Q(part__number__icontains=term)
            | Q(part__name__icontains=term)
            | Q(part__project__code__icontains=term)
            | Q(part__project__name__icontains=term)
        )
        .select_related("part", "part__project", "created_by")
        .order_by("-created_at")[:limit]
    )
    snapshot_paths = list(
        ProjectSnapshotEntry.objects.filter(path__icontains=term)
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
