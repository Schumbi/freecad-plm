import re
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

from ..fcstd import (
    PLM_REVISION_PROPERTY,
    fcstd_with_plm_revision,
    read_uploaded_file,
    validate_fcstd_upload,
)
from ..models import (
    Annotation,
    AuditEvent,
    Part,
    ProjectSnapshotEntry,
    Revision,
)
from .common import PLMRevisionConflict


REVISION_CODE_PREFIX = "R"


REVISION_CODE_NUMBER_WIDTH = 4


REVISION_CODE_MAX_NUMBER = 10**REVISION_CODE_NUMBER_WIDTH - 1


REVISION_CODE_PATTERN = re.compile(
    rf"^{re.escape(REVISION_CODE_PREFIX)}(\d{{{REVISION_CODE_NUMBER_WIDTH}}})$"
)


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
        "technical_signature": metadata["technical_signature"],
        "freecad_document": metadata["freecad_document"],
    }
    if plm_revision:
        extracted["plm_revision"] = plm_revision
    return extracted


def revision_document_signature(revision):
    signature = (revision.extracted_metadata or {}).get("technical_signature", {})
    value = signature.get("document_xml_sha256")
    if not value:
        raise ValidationError("Basisrevision enthaelt keine technische FCStd-Signatur.")
    return value


def uploaded_document_signature(uploaded_file):
    metadata = validate_fcstd_upload(uploaded_file)
    return metadata["technical_signature"]["document_xml_sha256"]


def fcstd_model_changed(base_revision, uploaded_file):
    return revision_document_signature(base_revision) != uploaded_document_signature(
        uploaded_file
    )


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


def next_part_number(project, category=Part.Category.PART):
    prefix = "A" if category == Part.Category.ASSEMBLY else "P"
    max_number = 0
    for number in project.parts.values_list("number", flat=True):
        if len(number) == 5 and number.startswith(f"{prefix}-") and number[2:].isdigit():
            max_number = max(max_number, int(number[2:]))
    return f"{prefix}-{max_number + 1:03d}"


def part_category_from_metadata(metadata):
    document_kind = metadata.get("freecad_document", {}).get("document_kind")
    if document_kind == "assembly":
        return Part.Category.ASSEMBLY
    return Part.Category.PART


def part_identity_from_metadata(project, path, metadata):
    properties = metadata.get("freecad_document", {}).get("properties", {})
    category = part_category_from_metadata(metadata)
    freecad_id = (properties.get("Id") or "").strip()
    name = (properties.get("Label") or "").strip()
    if not name:
        name = PurePosixPath(path).stem

    if freecad_id:
        number = freecad_id
    else:
        existing_by_path = (
            ProjectSnapshotEntry.objects.filter(snapshot__project=project, path=path)
            .select_related("revision__part", "snapshot")
            .order_by("-snapshot__created_at", "-id")
            .first()
        )
        if existing_by_path:
            return existing_by_path.revision.part, False
        existing_by_name = project.parts.filter(name=name).order_by("id").first()
        if existing_by_name:
            return existing_by_name, False
        number = next_part_number(project, category)

    if project.parts.filter(number=number).exists():
        return project.parts.get(number=number), False

    part = Part.objects.create(
        project=project,
        number=number,
        name=name,
        category=category,
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


def create_annotation(
    *,
    part,
    created_by,
    text,
    revision=None,
    object_name="",
    subelement="",
):
    object_name = object_name.strip() if isinstance(object_name, str) else ""
    subelement = subelement.strip() if isinstance(subelement, str) else ""
    annotation = Annotation.objects.create(
        project=part.project,
        part=part,
        revision=revision,
        object_name=object_name,
        subelement=subelement,
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


@transaction.atomic
def obsolete_revision(revision, actor):
    if revision.status == Revision.Status.OBSOLETE:
        raise ValidationError("Diese Revision ist bereits obsolet.")
    if revision.status != Revision.Status.RELEASED:
        raise ValidationError(
            "Nur freigegebene Revisionen koennen als obsolet markiert werden."
        )

    revision.status = Revision.Status.OBSOLETE
    revision.save(update_fields=["status", "updated_at"])

    AuditEvent.objects.create(
        actor=actor,
        action=AuditEvent.Action.REVISION_OBSOLETED,
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
