import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

from .fcstd import (
    PLM_REVISION_PROPERTY,
    fcstd_with_plm_revision,
    read_uploaded_file,
    validate_fcstd_upload,
)
from .models import (
    Annotation,
    AuditEvent,
    Checkout,
    Part,
    ProjectSnapshot,
    ProjectSnapshotEntry,
    Revision,
)


REVISION_CODE_PREFIX = "R"
REVISION_CODE_NUMBER_WIDTH = 4
REVISION_CODE_MAX_NUMBER = 10**REVISION_CODE_NUMBER_WIDTH - 1
REVISION_CODE_PATTERN = re.compile(
    rf"^{re.escape(REVISION_CODE_PREFIX)}(\d{{{REVISION_CODE_NUMBER_WIDTH}}})$"
)


@dataclass(frozen=True)
class ProjectZipMember:
    path: str
    data: bytes


class PLMRevisionConflict(ValidationError):
    def __init__(self, *, expected, actual, original_filename, original_sha256):
        if actual:
            message = (
                f"{PLM_REVISION_PROPERTY} in der FCStd-Datei ist {actual}, "
                f"erwartet wird {expected}."
            )
        else:
            message = (
                f"{PLM_REVISION_PROPERTY} fehlt in der FCStd-Datei; "
                f"erwartet wird {expected}."
            )
        super().__init__(message)
        self.expected = expected
        self.actual = actual
        self.original_filename = original_filename
        self.original_sha256 = original_sha256


def revision_code_number(code):
    match = REVISION_CODE_PATTERN.fullmatch(code or "")
    if not match:
        return None

    number = int(match.group(1))
    if number == 0:
        return None
    return number


def format_revision_code(number):
    if number < 1 or number > REVISION_CODE_MAX_NUMBER:
        highest_code = (
            f"{REVISION_CODE_PREFIX}"
            f"{REVISION_CODE_MAX_NUMBER:0{REVISION_CODE_NUMBER_WIDTH}d}"
        )
        raise ValidationError(
            f"Revisionscode muss zwischen {REVISION_CODE_PREFIX}0001 "
            f"und {highest_code} liegen."
        )
    return f"{REVISION_CODE_PREFIX}{number:0{REVISION_CODE_NUMBER_WIDTH}d}"


def next_revision_code(part):
    max_number = 0
    for code in part.revisions.values_list("revision_code", flat=True):
        number = revision_code_number(code)
        if number is not None:
            max_number = max(max_number, number)
    return format_revision_code(max_number + 1)


def revision_metadata_from_validation(metadata, plm_revision=None):
    extracted = {
        "zip_member_count": metadata["zip_member_count"],
        "has_document_xml": metadata["has_document_xml"],
        "has_gui_document_xml": metadata["has_gui_document_xml"],
        "freecad_document": metadata["freecad_document"],
    }
    if plm_revision:
        extracted["plm_revision"] = plm_revision
    return extracted


def freecad_plm_revision(metadata):
    return (
        metadata.get("freecad_document", {})
        .get("properties", {})
        .get(PLM_REVISION_PROPERTY, "")
        .strip()
    )


def existing_revision_for_upload_hash(part, sha256):
    for revision in part.revisions.all():
        plm_revision = (revision.extracted_metadata or {}).get("plm_revision", {})
        if revision.sha256 == sha256 or plm_revision.get("original_upload_sha256") == sha256:
            return revision
    return None


def validate_revision_code_argument(revision_code):
    if revision_code is None:
        return None
    number = revision_code_number(revision_code)
    if number is None or format_revision_code(number) != revision_code:
        raise ValidationError("Manuelle Revisionscodes muessen das Format R0001 verwenden.")
    return revision_code


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
    existing = existing_revision_for_upload_hash(part, metadata["sha256"])
    if existing:
        return existing, False

    revision_code = next_revision_code(part)
    uploaded_plm_revision = freecad_plm_revision(metadata)
    original_sha256 = metadata["sha256"]
    normalized = uploaded_plm_revision != revision_code
    if normalized:
        data = fcstd_with_plm_revision(data, revision_code)
        metadata = validate_fcstd_upload(
            SimpleUploadedFile(PurePosixPath(path).name, data)
        )

    revision = Revision.objects.create(
        part=part,
        revision_code=revision_code,
        status=Revision.Status.DRAFT,
        file=ContentFile(data, name=PurePosixPath(path).name),
        original_filename=PurePosixPath(path).name,
        sha256=metadata["sha256"],
        size_bytes=metadata["size_bytes"],
        extracted_metadata=revision_metadata_from_validation(
            metadata,
            {
                "expected": revision_code,
                "uploaded": uploaded_plm_revision,
                "normalized": normalized,
                "original_upload_sha256": original_sha256,
                "stored_sha256": metadata["sha256"],
            },
        ),
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


def manifest_entries_for_revision(revision, snapshot=None):
    root_entry = snapshot_entry_for_revision(revision, snapshot=snapshot)
    references = revision_reference_files(revision)
    if references and root_entry is None:
        raise ValidationError(
            "Referenzierte Revisionen koennen nur mit Projektstand ausgecheckt werden."
        )
    if root_entry is None:
        return [
            {
                "path": revision.original_filename,
                "revision": revision,
                "is_root": True,
            }
        ]
    return [
        {
            "path": entry.path,
            "revision": entry.revision,
            "is_root": entry.id == root_entry.id,
        }
        for entry in snapshot_entries_with_references(root_entry)
    ]


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
        "files": [
            {
                "path": entry["path"],
                "is_root": entry["is_root"],
                "revision_id": entry["revision"].id,
                "part_id": entry["revision"].part_id,
                "part_number": entry["revision"].part.number,
                "revision_code": entry["revision"].revision_code,
                "filename": entry["revision"].original_filename,
                "sha256": entry["revision"].sha256,
                "size_bytes": entry["revision"].size_bytes,
            }
            for entry in entries
        ],
    }


@transaction.atomic
def create_checkout(base_revision, checked_out_by, snapshot=None, workspace_hint=""):
    part = base_revision.part
    if Checkout.objects.filter(part=part, status=Checkout.Status.ACTIVE).exists():
        raise ValidationError("Dieses Teil ist bereits ausgecheckt.")
    manifest_entries_for_revision(base_revision, snapshot=snapshot)
    checkout = Checkout.objects.create(
        part=part,
        base_revision=base_revision,
        snapshot=snapshot,
        checked_out_by=checked_out_by,
        workspace_hint=workspace_hint.strip(),
    )
    AuditEvent.objects.create(
        actor=checked_out_by,
        action=AuditEvent.Action.CHECKOUT_CREATED,
        object_repr=str(checkout),
        metadata={
            "checkout_id": checkout.id,
            "part_id": part.id,
            "base_revision_id": base_revision.id,
            "base_revision_code": base_revision.revision_code,
            "snapshot_id": snapshot.id if snapshot else None,
        },
    )
    return checkout


@transaction.atomic
def cancel_checkout(checkout, actor):
    if checkout.status != Checkout.Status.ACTIVE:
        raise ValidationError("Nur aktive Checkouts koennen abgebrochen werden.")
    checkout.status = Checkout.Status.CANCELED
    checkout.canceled_at = timezone.now()
    checkout.save(update_fields=["status", "canceled_at", "updated_at"])
    AuditEvent.objects.create(
        actor=actor,
        action=AuditEvent.Action.CHECKOUT_CANCELED,
        object_repr=str(checkout),
        metadata={
            "checkout_id": checkout.id,
            "part_id": checkout.part_id,
            "base_revision_id": checkout.base_revision_id,
        },
    )
    return checkout


@transaction.atomic
def checkin_checkout(checkout, uploaded_file, actor, notes=""):
    if checkout.status != Checkout.Status.ACTIVE:
        raise ValidationError("Nur aktive Checkouts koennen eingecheckt werden.")
    revision = create_revision_from_upload(
        part=checkout.part,
        uploaded_file=uploaded_file,
        created_by=actor,
        notes=notes,
    )
    checkout.status = Checkout.Status.COMPLETED
    checkout.completed_revision = revision
    checkout.completed_at = timezone.now()
    checkout.save(
        update_fields=[
            "status",
            "completed_revision",
            "completed_at",
            "updated_at",
        ]
    )
    AuditEvent.objects.create(
        actor=actor,
        action=AuditEvent.Action.CHECKOUT_COMPLETED,
        object_repr=str(checkout),
        metadata={
            "checkout_id": checkout.id,
            "part_id": checkout.part_id,
            "base_revision_id": checkout.base_revision_id,
            "completed_revision_id": revision.id,
            "completed_revision_code": revision.revision_code,
        },
    )
    return revision


def create_annotation(
    *,
    part,
    created_by,
    text,
    revision=None,
    object_name="",
    subelement="",
):
    annotation = Annotation.objects.create(
        project=part.project,
        part=part,
        revision=revision,
        object_name=object_name.strip(),
        subelement=subelement.strip(),
        text=text.strip(),
        created_by=created_by,
    )
    AuditEvent.objects.create(
        actor=created_by,
        action=AuditEvent.Action.ANNOTATION_CREATED,
        object_repr=str(annotation),
        metadata={
            "annotation_id": annotation.id,
            "part_id": part.id,
            "revision_id": revision.id if revision else None,
            "object_name": annotation.object_name,
            "subelement": annotation.subelement,
        },
    )
    return annotation


@transaction.atomic
def create_revision_from_upload(
    part,
    uploaded_file,
    created_by,
    revision_code=None,
    normalize_plm_revision=False,
    notes="",
):
    metadata = validate_fcstd_upload(uploaded_file)
    file_data = read_uploaded_file(uploaded_file)
    code = validate_revision_code_argument(revision_code) or next_revision_code(part)
    uploaded_plm_revision = freecad_plm_revision(metadata)
    original_sha256 = metadata["sha256"]

    if existing_revision_for_upload_hash(part, original_sha256):
        raise ValidationError(
            "Diese FCStd-Datei wurde fuer dieses Teil bereits hochgeladen."
        )

    normalized = False
    if uploaded_plm_revision != code:
        if not normalize_plm_revision:
            raise PLMRevisionConflict(
                expected=code,
                actual=uploaded_plm_revision,
                original_filename=metadata["original_filename"],
                original_sha256=original_sha256,
            )
        file_data = fcstd_with_plm_revision(file_data, code)
        uploaded_file = ContentFile(file_data, name=metadata["original_filename"])
        metadata = validate_fcstd_upload(
            SimpleUploadedFile(metadata["original_filename"], file_data)
        )
        normalized = True

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
        notes=notes.strip(),
        extracted_metadata=revision_metadata_from_validation(
            metadata,
            {
                "expected": code,
                "uploaded": uploaded_plm_revision,
                "normalized": normalized,
                "original_upload_sha256": original_sha256,
                "stored_sha256": metadata["sha256"],
            },
        ),
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
            "plm_revision": revision.extracted_metadata["plm_revision"],
            "change_summary": revision.notes,
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
