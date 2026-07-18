import re
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from ..fcstd import (
    DEFAULT_PLM_MAX_PROJECT_ZIP_BYTES,
    DEFAULT_PLM_MAX_ZIP_MEMBER_BYTES,
    DEFAULT_PLM_MAX_ZIP_MEMBERS,
    DEFAULT_PLM_MAX_ZIP_UNCOMPRESSED_BYTES,
    read_uploaded_file,
    setting_int,
    validate_fcstd_upload,
    validate_uploaded_file_size,
    validate_zip_archive_budget,
)
from ..models import (
    Annotation,
    AuditEvent,
    Checkout,
    ExportJob,
    ManufacturingFile,
    ManufacturingRun,
    ManufacturingRunAttachment,
    ProjectSnapshot,
    ProjectSnapshotEntry,
    Revision,
    RevisionArtifact,
)
from .common import ProjectZipMember, safe_snapshot_path
from .revisions import create_or_reuse_revision, part_identity_from_metadata


SNAPSHOT_VERSION_SUFFIX_RE = re.compile(r" - (?:Checkout \d+|V\d+)$")


def iter_fcstd_zip_members(uploaded_zip):
    max_project_zip_bytes = setting_int(
        "PLM_MAX_PROJECT_ZIP_BYTES",
        DEFAULT_PLM_MAX_PROJECT_ZIP_BYTES,
    )
    validate_uploaded_file_size(
        uploaded_zip,
        max_project_zip_bytes,
        "Die Projektdatei",
    )
    data = read_uploaded_file(uploaded_zip)
    if len(data) > max_project_zip_bytes:
        raise ValidationError("Die Projektdatei ist groesser als das erlaubte Upload-Budget.")
    try:
        with ZipFile(BytesIO(data)) as archive:
            validate_zip_archive_budget(
                archive,
                label="Die Projektdatei",
                max_members=setting_int(
                    "PLM_MAX_ZIP_MEMBERS",
                    DEFAULT_PLM_MAX_ZIP_MEMBERS,
                ),
                max_uncompressed_bytes=setting_int(
                    "PLM_MAX_ZIP_UNCOMPRESSED_BYTES",
                    DEFAULT_PLM_MAX_ZIP_UNCOMPRESSED_BYTES,
                ),
                max_member_bytes=setting_int(
                    "PLM_MAX_ZIP_MEMBER_BYTES",
                    DEFAULT_PLM_MAX_ZIP_MEMBER_BYTES,
                ),
            )
            for info in archive.infolist():
                if info.is_dir():
                    continue
                path = safe_snapshot_path(info.filename)
                if not path.lower().endswith(".fcstd"):
                    continue
                yield ProjectZipMember(path=path, data=archive.read(info))
    except BadZipFile as exc:
        raise ValidationError("Die Projektdatei muss ein gueltiges ZIP-Archiv sein.") from exc


@transaction.atomic
def import_project_snapshot(project, uploaded_zip, created_by, name=""):
    members = list(iter_fcstd_zip_members(uploaded_zip))
    if not members:
        raise ValidationError("Das ZIP enthaelt keine FCStd-Dateien.")

    snapshot = ProjectSnapshot.objects.create(
        project=project,
        name=name.strip() or PurePosixPath(uploaded_zip.name).stem,
        created_by=created_by,
    )
    import_summary = {
        "created_parts": 0,
        "created_revisions": 0,
        "reused_revisions": 0,
        "files": [],
    }

    for member in members:
        metadata = validate_fcstd_upload(
            SimpleUploadedFile(PurePosixPath(member.path).name, member.data)
        )
        part, created_part = part_identity_from_metadata(project, member.path, metadata)
        if created_part:
            import_summary["created_parts"] += 1
        if created_part:
            AuditEvent.objects.create(
                actor=created_by,
                action=AuditEvent.Action.PART_CREATED,
                object_repr=str(part),
                metadata={
                    "project_id": project.id,
                    "part_id": part.id,
                    "part_number": part.number,
                    "category": part.category,
                    "snapshot_path": member.path,
                },
            )
        revision, created_revision = create_or_reuse_revision(
            part,
            member.path,
            member.data,
            created_by,
        )
        if created_revision:
            import_summary["created_revisions"] += 1
        else:
            import_summary["reused_revisions"] += 1
        import_summary["files"].append(
            {
                "path": member.path,
                "part_id": part.id,
                "part_number": part.number,
                "revision_id": revision.id,
                "revision_code": revision.revision_code,
                "created_part": created_part,
                "created_revision": created_revision,
            }
        )
        if created_revision:
            AuditEvent.objects.create(
                actor=created_by,
                action=AuditEvent.Action.REVISION_UPLOADED,
                object_repr=str(revision),
                metadata={
                    "part_id": part.id,
                    "revision_id": revision.id,
                    "revision_code": revision.revision_code,
                    "sha256": revision.sha256,
                    "original_filename": revision.original_filename,
                    "snapshot_path": member.path,
                    "plm_revision": revision.extracted_metadata.get("plm_revision", {}),
                },
            )
        ProjectSnapshotEntry.objects.create(
            snapshot=snapshot,
            path=member.path,
            revision=revision,
        )

    AuditEvent.objects.create(
        actor=created_by,
        action=AuditEvent.Action.PROJECT_SNAPSHOT_CREATED,
        object_repr=str(snapshot),
        metadata={
            "project_id": project.id,
            "snapshot_id": snapshot.id,
            "entry_count": snapshot.entries.count(),
            "import_summary": import_summary,
        },
    )
    snapshot.import_summary = import_summary
    return snapshot


@transaction.atomic
def delete_project_tree(project, actor):
    project = (
        type(project)
        .objects.select_for_update()
        .prefetch_related("parts__revisions__artifacts")
        .get(pk=project.pk)
    )
    summary = {
        "project_id": project.id,
        "project_code": project.code,
        "parts": project.parts.count(),
        "revisions": Revision.objects.filter(part__project=project).count(),
        "artifacts": RevisionArtifact.objects.filter(revision__part__project=project).count(),
        "manufacturing_files": ManufacturingFile.objects.filter(
            revision__part__project=project
        ).count(),
        "snapshots": project.snapshots.count(),
        "annotations": project.annotations.count(),
        "checkouts": Checkout.objects.filter(part__project=project).count(),
    }
    project_label = str(project)

    revisions = Revision.objects.filter(part__project=project)
    revision_files = [revision.file for revision in revisions if revision.file]
    artifact_files = [
        artifact.file
        for artifact in RevisionArtifact.objects.filter(revision__part__project=project)
        if artifact.file
    ]
    manufacturing_files = [
        item.file
        for item in ManufacturingFile.objects.filter(revision__part__project=project)
        if item.file
    ]
    manufacturing_thumbnails = [
        item.thumbnail
        for item in ManufacturingFile.objects.filter(revision__part__project=project)
        if item.thumbnail
    ]
    manufacturing_attachments = [
        item.file
        for item in ManufacturingRunAttachment.objects.filter(
            run__manufacturing_file__revision__part__project=project
        )
        if item.file
    ]

    AuditEvent.objects.create(
        actor=actor,
        action=AuditEvent.Action.PROJECT_DELETED,
        object_repr=project_label,
        metadata=summary,
    )

    Annotation.objects.filter(project=project).delete()
    Checkout.objects.filter(part__project=project).delete()
    ProjectSnapshotEntry.objects.filter(snapshot__project=project).delete()
    ProjectSnapshot.objects.filter(project=project).delete()
    ManufacturingRunAttachment.objects.filter(
        run__manufacturing_file__revision__part__project=project
    ).delete()
    ManufacturingRun.objects.filter(
        manufacturing_file__revision__part__project=project
    ).delete()
    ManufacturingFile.objects.filter(revision__part__project=project).delete()
    RevisionArtifact.objects.filter(revision__part__project=project).delete()
    ExportJob.objects.filter(revision__part__project=project).delete()
    revisions.delete()
    project.parts.all().delete()
    project.delete()

    for field_file in [
        *manufacturing_attachments,
        *manufacturing_thumbnails,
        *manufacturing_files,
        *artifact_files,
        *revision_files,
    ]:
        field_file.delete(save=False)

    return summary


def revision_reference_files(revision):
    document = (revision.extracted_metadata or {}).get("freecad_document", {})
    return [reference.get("file") for reference in document.get("references", []) if reference.get("file")]


def resolve_reference_path(source_path, reference_file):
    source_dir = PurePosixPath(source_path).parent
    if str(source_dir) == ".":
        return str(PurePosixPath(reference_file))
    return str(source_dir / reference_file)


def snapshot_entries_with_references(root_entry):
    entries_by_path = {
        entry.path: entry
        for entry in root_entry.snapshot.entries.select_related("revision", "revision__part")
    }
    entries_by_name = {
        PurePosixPath(entry.path).name: entry
        for entry in root_entry.snapshot.entries.select_related("revision", "revision__part")
    }
    selected = {}
    queue = [root_entry]

    while queue:
        entry = queue.pop(0)
        if entry.path in selected:
            continue
        selected[entry.path] = entry

        for reference_file in revision_reference_files(entry.revision):
            reference_path = resolve_reference_path(entry.path, reference_file)
            referenced_entry = entries_by_path.get(reference_path) or entries_by_name.get(
                PurePosixPath(reference_file).name
            )
            if referenced_entry and referenced_entry.path not in selected:
                queue.append(referenced_entry)

    return [selected[path] for path in sorted(selected)]


def snapshot_entry_for_revision(revision, snapshot=None):
    entries = revision.snapshot_entries.select_related(
        "snapshot",
        "snapshot__project",
        "revision",
        "revision__part",
    )
    if snapshot is not None:
        entries = entries.filter(snapshot=snapshot)
    return entries.order_by("-snapshot__created_at", "path").first()


def snapshot_base_name(name):
    result = (name or "").strip()
    while True:
        stripped = SNAPSHOT_VERSION_SUFFIX_RE.sub("", result)
        if stripped == result:
            return result
        result = stripped


def checkout_snapshot_name(source_snapshot_name, checkout_id):
    return f"{snapshot_base_name(source_snapshot_name)} - V{checkout_id}"


def create_snapshot_from_checkout_revisions(checkout, actor, revisions):
    removed_paths = set(checkout.removed_paths or [])
    additions = {
        addition.path: addition.revision
        for addition in checkout.added_files.select_related("revision").order_by("path")
    }
    if not checkout.snapshot_id or (not revisions and not removed_paths and not additions):
        return None

    replacements = {item["path"]: item["revision"] for item in revisions}
    snapshot = ProjectSnapshot.objects.create(
        project=checkout.part.project,
        name=checkout_snapshot_name(checkout.snapshot.name, checkout.id),
        created_by=actor,
    )
    copied_paths = set()
    for entry in checkout.snapshot.entries.select_related("revision").order_by("path"):
        if entry.path in removed_paths:
            continue
        ProjectSnapshotEntry.objects.create(
            snapshot=snapshot,
            path=entry.path,
            revision=replacements.get(
                entry.path,
                additions.get(entry.path, entry.revision),
            ),
        )
        copied_paths.add(entry.path)
    for path, revision in additions.items():
        if path in copied_paths or path in removed_paths:
            continue
        ProjectSnapshotEntry.objects.create(
            snapshot=snapshot,
            path=path,
            revision=replacements.get(path, revision),
        )
    AuditEvent.objects.create(
        actor=actor,
        action=AuditEvent.Action.PROJECT_SNAPSHOT_CREATED,
        object_repr=str(snapshot),
        metadata={
            "project_id": checkout.part.project_id,
            "snapshot_id": snapshot.id,
            "source_snapshot_id": checkout.snapshot_id,
            "checkout_id": checkout.id,
            "entry_count": snapshot.entries.count(),
            "updated_paths": sorted(replacements),
            "removed_paths": sorted(removed_paths),
            "added_paths": sorted(additions),
        },
    )
    return snapshot
