from hashlib import sha256
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction

from ..fcstd import setting_int
from ..models import ProjectDocument, ProjectDocumentVersion, ProjectSnapshotDocument
from .common import safe_snapshot_path


def clean_document_path(path):
    path = safe_snapshot_path(path)
    if len(path) > 500 or path in {".", ""} or path.endswith("/"):
        raise ValidationError("Ungültiger Dokumentpfad.")
    if len(PurePosixPath(path).name) > 255:
        raise ValidationError("Der Dateiname darf höchstens 255 Zeichen lang sein.")
    return path


@transaction.atomic
def upload_document(project, path, uploaded_file, actor):
    path = clean_document_path(path)
    limit = setting_int("PLM_MAX_PROJECT_DOCUMENT_BYTES", 200 * 1024 * 1024)
    if uploaded_file.size > limit:
        raise ValidationError(f"Die Projektdatei darf höchstens {limit} Bytes groß sein.")
    data = uploaded_file.read(limit + 1)
    if len(data) > limit:
        raise ValidationError(f"Die Projektdatei darf höchstens {limit} Bytes groß sein.")
    digest = sha256(data).hexdigest()
    document, _ = ProjectDocument.objects.select_for_update().get_or_create(project=project, path=path)
    latest = document.versions.order_by("-number").first()
    if latest and latest.sha256 == digest:
        if document.is_archived:
            document.is_archived = False
            document.save(update_fields=["is_archived", "updated_at"])
        return latest, False
    filename = PurePosixPath(path).name
    version = ProjectDocumentVersion(document=document, number=(latest.number + 1 if latest else 1),
                                     filename=filename, sha256=digest, size=len(data), created_by=actor)
    stored = document.versions.filter(sha256=digest).first()
    if stored:
        version.file.name = stored.file.name
    else:
        version.file.save(filename, ContentFile(data), save=False)
    version.save()
    if document.is_archived:
        document.is_archived = False
        document.save(update_fields=["is_archived", "updated_at"])
    return version, True


def capture_current_documents(snapshot):
    for document in snapshot.project.documents.filter(is_archived=False).prefetch_related("versions"):
        version = document.versions.order_by("-number").first()
        if version:
            ProjectSnapshotDocument.objects.create(snapshot=snapshot, version=version, path=document.path)


def copy_snapshot_documents(source, target):
    ProjectSnapshotDocument.objects.bulk_create([
        ProjectSnapshotDocument(snapshot=target, version_id=entry.version_id, path=entry.path)
        for entry in source.documents.all()
    ])
