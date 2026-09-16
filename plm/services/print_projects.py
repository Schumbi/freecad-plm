from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import AuditEvent, PrintProject, PrintProjectSnapshot


def _stored_file(field_file):
    if field_file and field_file.name:
        return field_file.storage, field_file.name
    return None


def _delete_stored_files(stored_files):
    for storage, name in stored_files:
        storage.delete(name)


@transaction.atomic
def delete_print_project(print_project, actor):
    print_project = (
        PrintProject.objects.select_for_update()
        .select_related("project", "primary_revision", "primary_revision__part")
        .prefetch_related("sources", "plates", "snapshots")
        .get(pk=print_project.pk)
    )
    if print_project.snapshots.exists():
        raise ValidationError(
            "Dieses Druckprojekt besitzt gespeicherte Druck-Snapshots und kann "
            "deshalb nicht gelöscht werden."
        )

    stored_files = []
    candidates = [print_project.slicer_file]
    candidates.extend(source.file for source in print_project.sources.all())
    candidates.extend(plate.preview for plate in print_project.plates.all())
    for field_file in candidates:
        item = _stored_file(field_file)
        if item is not None:
            stored_files.append(item)

    metadata = {
        "print_project_id": print_project.id,
        "project_id": print_project.project_id,
        "primary_revision_id": print_project.primary_revision_id,
        "code": print_project.code,
        "name": print_project.name,
        "slicer_original_filename": print_project.slicer_original_filename,
        "slicer_sha256": print_project.slicer_sha256,
        "source_count": print_project.sources.count(),
        "plate_count": print_project.plates.count(),
    }
    AuditEvent.objects.create(
        actor=actor,
        action=AuditEvent.Action.PRINT_PROJECT_DELETED,
        object_repr=str(print_project),
        metadata=metadata,
    )
    print_project.delete()
    transaction.on_commit(lambda: _delete_stored_files(stored_files))
    return metadata


@transaction.atomic
def delete_bambuddy_snapshot(snapshot):
    snapshot = (
        PrintProjectSnapshot.objects.select_for_update()
        .select_related("print_project")
        .get(pk=snapshot.pk)
    )
    stored_file = _stored_file(snapshot.file)
    metadata = {
        "print_project_snapshot_id": snapshot.id,
        "print_project_id": snapshot.print_project_id,
        "bambuddy_archive_id": snapshot.bambuddy_archive_id,
        "original_filename": snapshot.original_filename,
        "sha256": snapshot.sha256,
    }
    AuditEvent.objects.create(
        actor=None,
        action=AuditEvent.Action.BAMBUDDY_ARCHIVE_DELETED,
        object_repr=(
            f"{snapshot.print_project} / Bambuddy "
            f"{snapshot.bambuddy_archive_id}"
        ),
        metadata=metadata,
    )
    snapshot.delete()
    if stored_file is not None:
        transaction.on_commit(lambda: _delete_stored_files([stored_file]))
    return metadata
