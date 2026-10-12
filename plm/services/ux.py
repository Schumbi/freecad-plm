from pathlib import PurePosixPath

from ..models import ManufacturingFile, AuditEvent, Revision
from .snapshots import (
    resolve_reference_path,
    revision_reference_files,
    unique_entries_by_filename,
)


def reference_checkins_for_part(part):
    """Show dependency-only check-ins without rewriting historical root notes."""
    events = list(AuditEvent.objects.filter(
        action=AuditEvent.Action.CHECKOUT_COMPLETED,
        metadata__part_id=part.id,
        metadata__completed_revision_id=None,
    ).select_related("actor").order_by("-created_at", "-id"))
    revision_ids = {
        item["revision_id"] for event in events
        for item in event.metadata.get("revisions", []) if item.get("revision_id")
    }
    notes = dict(Revision.objects.filter(id__in=revision_ids).values_list("id", "notes"))
    result = {}
    for event in events:
        comments = list(dict.fromkeys(
            notes.get(item.get("revision_id"), "") for item in event.metadata.get("revisions", [])
            if notes.get(item.get("revision_id"), "")
        ))
        summary = event.metadata.get("change_summary") or "\n".join(comments)
        result.setdefault(event.metadata.get("base_revision_id"), []).append({
            "timestamp": event.created_at, "actor": event.actor, "summary": summary,
        })
    return result


def part_lifecycle_events(part):
    events = []
    revisions = (
        part.revisions.select_related("created_by")
        .prefetch_related("manufacturing_files__runs", "manufacturing_files__machine")
        .order_by("-created_at")
    )
    for revision in revisions:
        events.append(
            {
                "kind": "revision",
                "timestamp": revision.created_at,
                "title": f"{revision.revision_code} angelegt",
                "detail": revision.original_filename,
                "status": revision.status,
                "revision": revision,
            }
        )
        if revision.released_at:
            events.append(
                {
                    "kind": "release",
                    "timestamp": revision.released_at,
                    "title": f"{revision.revision_code} freigegeben",
                    "detail": revision.notes,
                    "status": "released",
                    "revision": revision,
                }
            )
        for manufacturing_file in revision.manufacturing_files.all():
            is_slicer_project = (
                manufacturing_file.file_type
                == ManufacturingFile.FileType.SLICER_PROJECT_3MF
            )
            events.append(
                {
                    "kind": "slicer" if is_slicer_project else "manufacturing",
                    "timestamp": (
                        manufacturing_file.updated_at
                        if is_slicer_project
                        else manufacturing_file.created_at
                    ),
                    "title": (
                        "Slicer-Arbeitsstand synchronisiert"
                        if is_slicer_project
                        else "Fertigungsdatei hinterlegt"
                    ),
                    "detail": manufacturing_file.label
                    or manufacturing_file.original_filename,
                    "status": manufacturing_file.status,
                    "revision": revision,
                    "manufacturing_file": manufacturing_file,
                }
            )
            for run in manufacturing_file.runs.all():
                events.append(
                    {
                        "kind": "run",
                        "timestamp": run.finished_at or run.started_at or run.created_at,
                        "title": f"Fertigungslauf {run.get_status_display()}",
                        "detail": (
                            run.machine.name
                            if run.machine_id and run.machine
                            else manufacturing_file.machine_label
                        ),
                        "status": run.status,
                        "revision": revision,
                        "manufacturing_file": manufacturing_file,
                        "run": run,
                    }
                )
    return sorted(events, key=lambda event: event["timestamp"], reverse=True)


def assembly_bom_tree(revision):
    if revision is None:
        return None
    root_entry = (
        revision.snapshot_entries.select_related("snapshot", "revision__part")
        .order_by("-snapshot__created_at", "path")
        .first()
    )
    if root_entry is None:
        return _bom_node_without_snapshot(revision)

    entries = list(
        root_entry.snapshot.entries.select_related("revision", "revision__part")
    )
    entries_by_path = {entry.path: entry for entry in entries}
    entries_by_name = unique_entries_by_filename(entries)

    def build(entry, ancestry):
        node = _bom_entry_node(entry)
        if entry.path in ancestry:
            node["cycle"] = True
            return node
        next_ancestry = {*ancestry, entry.path}
        for reference in revision_reference_files(entry.revision):
            resolved = resolve_reference_path(entry.path, reference)
            child = entries_by_path.get(resolved) or entries_by_name.get(
                PurePosixPath(reference).name
            )
            if child is None:
                node["children"].append(
                    {
                        "label": PurePosixPath(reference).name,
                        "path": reference,
                        "missing": True,
                        "children": [],
                    }
                )
            else:
                node["children"].append(build(child, next_ancestry))
        return node

    tree = build(root_entry, set())
    tree["snapshot"] = root_entry.snapshot
    return tree


def _bom_entry_node(entry):
    part = entry.revision.part
    return {
        "label": f"{part.number} · {part.name}",
        "path": entry.path,
        "revision": entry.revision,
        "missing": False,
        "cycle": False,
        "children": [],
    }


def _bom_node_without_snapshot(revision):
    part = revision.part
    return {
        "label": f"{part.number} · {part.name}",
        "path": revision.original_filename,
        "revision": revision,
        "missing": False,
        "cycle": False,
        "snapshot": None,
        "children": [
            {
                "label": PurePosixPath(reference).name,
                "path": reference,
                "missing": True,
                "children": [],
            }
            for reference in revision_reference_files(revision)
        ],
    }
