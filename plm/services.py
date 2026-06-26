from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

from .fcstd import read_uploaded_file, validate_fcstd_upload
from .models import AuditEvent, Part, ProjectSnapshot, ProjectSnapshotEntry, Revision


@dataclass(frozen=True)
class ProjectZipMember:
    path: str
    data: bytes


def next_revision_code(part):
    max_number = 0
    for code in part.revisions.values_list("revision_code", flat=True):
        if len(code) == 5 and code.startswith("R") and code[1:].isdigit():
            max_number = max(max_number, int(code[1:]))
    return f"R{max_number + 1:04d}"


def next_part_number(project):
    max_number = 0
    for number in project.parts.values_list("number", flat=True):
        if len(number) == 5 and number.startswith("P-") and number[2:].isdigit():
            max_number = max(max_number, int(number[2:]))
    return f"P-{max_number + 1:03d}"


def safe_snapshot_path(path):
    normalized = PurePosixPath(path)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValidationError("ZIP enthaelt einen unsicheren Dateipfad.")
    return str(normalized)


def part_category_from_metadata(metadata):
    document_kind = metadata.get("freecad_document", {}).get("document_kind")
    if document_kind == "assembly":
        return Part.Category.ASSEMBLY
    return Part.Category.PART


def part_identity_from_metadata(project, path, metadata):
    properties = metadata.get("freecad_document", {}).get("properties", {})
    number = (properties.get("Id") or "").strip()
    if not number:
        number = PurePosixPath(path).stem

    name = (properties.get("Label") or "").strip()
    if not name:
        name = PurePosixPath(path).stem

    if project.parts.filter(number=number).exists():
        return project.parts.get(number=number), False

    part = Part.objects.create(
        project=project,
        number=number,
        name=name,
        category=part_category_from_metadata(metadata),
    )
    return part, True


def create_or_reuse_revision(part, path, data, created_by):
    upload = SimpleUploadedFile(PurePosixPath(path).name, data)
    metadata = validate_fcstd_upload(upload)
    existing = part.revisions.filter(sha256=metadata["sha256"]).first()
    if existing:
        return existing, False

    revision = Revision.objects.create(
        part=part,
        revision_code=next_revision_code(part),
        status=Revision.Status.DRAFT,
        file=ContentFile(data, name=PurePosixPath(path).name),
        original_filename=PurePosixPath(path).name,
        sha256=metadata["sha256"],
        size_bytes=metadata["size_bytes"],
        extracted_metadata={
            "zip_member_count": metadata["zip_member_count"],
            "has_document_xml": metadata["has_document_xml"],
            "has_gui_document_xml": metadata["has_gui_document_xml"],
            "freecad_document": metadata["freecad_document"],
        },
        created_by=created_by,
    )
    return revision, True


def iter_fcstd_zip_members(uploaded_zip):
    data = read_uploaded_file(uploaded_zip)
    try:
        with ZipFile(BytesIO(data)) as archive:
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

    for member in members:
        metadata = validate_fcstd_upload(
            SimpleUploadedFile(PurePosixPath(member.path).name, member.data)
        )
        part, created_part = part_identity_from_metadata(project, member.path, metadata)
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
        },
    )
    return snapshot


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


@transaction.atomic
def create_revision_from_upload(part, uploaded_file, created_by, revision_code=None):
    metadata = validate_fcstd_upload(uploaded_file)
    file_data = read_uploaded_file(uploaded_file)
    code = revision_code or next_revision_code(part)

    if part.revisions.filter(sha256=metadata["sha256"]).exists():
        raise ValidationError(
            "Diese FCStd-Datei wurde fuer dieses Teil bereits hochgeladen."
        )

    revision = Revision.objects.create(
        part=part,
        revision_code=code,
        status=Revision.Status.DRAFT,
        file=uploaded_file,
        original_filename=metadata["original_filename"],
        sha256=metadata["sha256"],
        size_bytes=metadata["size_bytes"],
        extracted_metadata={
            "zip_member_count": metadata["zip_member_count"],
            "has_document_xml": metadata["has_document_xml"],
            "has_gui_document_xml": metadata["has_gui_document_xml"],
            "freecad_document": metadata["freecad_document"],
        },
        created_by=created_by,
    )

    if revision.size_bytes != len(file_data):
        raise ValueError("Stored revision size does not match uploaded data.")

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
        },
    )
    return revision


@transaction.atomic
def release_revision(revision, released_by):
    if revision.status == Revision.Status.RELEASED:
        raise ValidationError("Diese Revision ist bereits freigegeben.")
    if revision.status != Revision.Status.DRAFT:
        raise ValidationError("Nur Entwurfsrevisionen koennen freigegeben werden.")

    revision.status = Revision.Status.RELEASED
    revision.released_at = timezone.now()
    revision.save(update_fields=["status", "released_at", "updated_at"])

    AuditEvent.objects.create(
        actor=released_by,
        action=AuditEvent.Action.REVISION_RELEASED,
        object_repr=str(revision),
        metadata={
            "part_id": revision.part_id,
            "revision_id": revision.id,
            "revision_code": revision.revision_code,
            "sha256": revision.sha256,
            "original_filename": revision.original_filename,
        },
    )
    return revision
