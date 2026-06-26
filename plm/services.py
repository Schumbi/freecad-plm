from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .fcstd import read_uploaded_file, validate_fcstd_upload
from .models import AuditEvent, Revision


def next_revision_code(part):
    max_number = 0
    for code in part.revisions.values_list("revision_code", flat=True):
        if len(code) == 5 and code.startswith("R") and code[1:].isdigit():
            max_number = max(max_number, int(code[1:]))
    return f"R{max_number + 1:04d}"


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
