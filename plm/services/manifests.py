from django.core.exceptions import ValidationError

from .common import safe_snapshot_path
from .snapshots import (
    revision_reference_files,
    snapshot_entries_with_references,
    snapshot_entry_for_revision,
)


def manifest_entries_for_revision(revision, snapshot=None):
    root_entry = snapshot_entry_for_revision(revision, snapshot=snapshot)
    references = revision_reference_files(revision)
    if references and root_entry is None:
        raise ValidationError(
            "Referenzierte Revisionen koennen nur mit Projektstand geladen werden."
        )
    if root_entry is None:
        return [
            {
                "path": safe_snapshot_path(revision.original_filename),
                "revision": revision,
                "is_root": True,
            }
        ]
    return [
        {
            "path": safe_snapshot_path(entry.path),
            "revision": entry.revision,
            "is_root": entry.id == root_entry.id,
        }
        for entry in snapshot_entries_with_references(root_entry)
    ]


def manifest_file_payload(entry):
    revision = entry["revision"]
    return {
        "path": entry["path"],
        "is_root": entry["is_root"],
        "revision_id": revision.id,
        "part_id": revision.part_id,
        "part_number": revision.part.number,
        "revision_code": revision.revision_code,
        "filename": revision.original_filename,
        "sha256": revision.sha256,
        "size_bytes": revision.size_bytes,
    }


def revision_manifest(revision, snapshot=None):
    entries = manifest_entries_for_revision(revision, snapshot=snapshot)
    return {
        "project": {
            "id": revision.part.project_id,
            "code": revision.part.project.code,
            "name": revision.part.project.name,
        },
        "part": {
            "id": revision.part_id,
            "number": revision.part.number,
            "name": revision.part.name,
            "category": revision.part.category,
        },
        "revision": {
            "id": revision.id,
            "revision_code": revision.revision_code,
            "status": revision.status,
            "original_filename": revision.original_filename,
            "sha256": revision.sha256,
            "size_bytes": revision.size_bytes,
        },
        "snapshot": (
            {
                "id": snapshot.id,
                "name": snapshot.name,
            }
            if snapshot is not None
            else None
        ),
        "files": [manifest_file_payload(entry) for entry in entries],
    }


def checkout_manifest(checkout):
    entries = manifest_entries_for_revision(
        checkout.base_revision,
        snapshot=checkout.snapshot,
    )
    return {
        "checkout_id": checkout.id,
        "status": checkout.status,
        "project": {
            "id": checkout.part.project_id,
            "code": checkout.part.project.code,
            "name": checkout.part.project.name,
        },
        "part": {
            "id": checkout.part_id,
            "number": checkout.part.number,
            "name": checkout.part.name,
            "category": checkout.part.category,
        },
        "base_revision": {
            "id": checkout.base_revision_id,
            "revision_code": checkout.base_revision.revision_code,
            "sha256": checkout.base_revision.sha256,
        },
        "snapshot": (
            {
                "id": checkout.snapshot_id,
                "name": checkout.snapshot.name,
            }
            if checkout.snapshot_id
            else None
        ),
        "files": [manifest_file_payload(entry) for entry in entries],
    }


def manifest_entries_by_path(checkout):
    return {
        entry["path"]: entry
        for entry in manifest_entries_for_revision(
            checkout.base_revision,
            snapshot=checkout.snapshot,
        )
    }
