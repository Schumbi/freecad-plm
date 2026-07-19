from io import BytesIO
from pathlib import PurePosixPath
from uuid import uuid4
from zipfile import ZipFile
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import FileResponse, HttpResponseForbidden, HttpResponseNotFound
from django.urls import reverse
from ..derivatives import revision_has_complete_png_views, revision_has_pending_png_job, revision_png_view_names
from ..forms import user_role
from ..freecadcmd import PREVIEW_GENERATOR_VERSION, create_export_job, process_export_job
from ..models import ExportJob, ManufacturingFile, RevisionArtifact
from ..permissions import ROLE_ADMIN, is_plm_admin
from ..services import revision_reference_files, snapshot_entries_with_references


PENDING_REVISION_UPLOAD_SESSION_KEY = "pending_revision_upload"


VIEWER_PREVIEW_VIEW_NAME = "viewer-preview"


VIEWER_FALLBACK_VIEW_NAME = "preview"


VIEWER_SUPPORTED_ARTIFACT_TYPES = {
    RevisionArtifact.ArtifactType.STL,
    RevisionArtifact.ArtifactType.THREEMF,
    RevisionArtifact.ArtifactType.STEP,
}


VIEWER_SUPPORTED_MANUFACTURING_TYPES = {
    ManufacturingFile.FileType.SLICER_3MF,
    ManufacturingFile.FileType.STL_PRINT,
    ManufacturingFile.FileType.STEP_VENDOR,
}


VIEWER_CONTENT_TYPES = {
    "stl": "model/stl",
    "3mf": "model/3mf",
}


EXPORT_JOB_ACTIVE_STATUSES = (
    ExportJob.Status.QUEUED,
    ExportJob.Status.RUNNING,
)


def admin_required_response(request):
    if is_plm_admin(request.user):
        return None
    return HttpResponseForbidden("Keine Berechtigung fuer die Verwaltung.")


def active_admin_count(exclude_user=None):
    users = get_user_model().objects.filter(is_active=True)
    if exclude_user is not None and exclude_user.pk:
        users = users.exclude(pk=exclude_user.pk)
    return users.filter(groups__name=ROLE_ADMIN).distinct().count() + users.filter(
        is_superuser=True
    ).count()


def validate_user_admin_safety(target_user, actor, role, is_active):
    if not target_user.pk:
        return None
    if target_user.pk == actor.pk:
        if not is_active:
            return "Du kannst deinen eigenen Benutzer nicht deaktivieren."
        if role != ROLE_ADMIN and not target_user.is_superuser:
            return "Du kannst dir nicht selbst die Admin-Rolle entziehen."
    if user_role(target_user) == ROLE_ADMIN or target_user.is_superuser:
        if (not is_active or (role != ROLE_ADMIN and not target_user.is_superuser)) and active_admin_count(
            exclude_user=target_user,
        ) == 0:
            return "Der letzte aktive Admin darf nicht deaktiviert oder degradiert werden."
    return None


def token_status(token):
    if token.is_revoked:
        return "Widerrufen"
    if token.is_expired():
        return "Abgelaufen"
    return "Aktiv"


def save_pending_revision_upload(part, uploaded_file, conflict, change_summary=""):
    pending_name = (
        f"pending_uploads/{uuid4().hex}-{PurePosixPath(uploaded_file.name).name}"
    )
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    saved_name = default_storage.save(pending_name, ContentFile(uploaded_file.read()))

    pending = {
        "part_id": part.id,
        "storage_name": saved_name,
        "original_filename": PurePosixPath(uploaded_file.name).name,
        "expected": conflict.expected,
        "actual": conflict.actual,
        "original_sha256": conflict.original_sha256,
        "change_summary": change_summary,
    }
    return pending


def clear_pending_revision_upload(request):
    pending = request.session.pop(PENDING_REVISION_UPLOAD_SESSION_KEY, None)
    request.session.modified = True
    if pending and default_storage.exists(pending["storage_name"]):
        default_storage.delete(pending["storage_name"])
    return pending


def snapshot_entry_for_revision_download(revision):
    if not revision_reference_files(revision):
        return None
    return (
        revision.snapshot_entries.select_related("snapshot", "snapshot__project")
        .order_by("-snapshot__created_at", "path")
        .first()
    )


def referenced_revision_zip_response(root_entry):
    entries = snapshot_entries_with_references(root_entry)
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for entry in entries:
            with entry.revision.file.open("rb") as fh:
                archive.writestr(entry.path, fh.read())
    buffer.seek(0)
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=f"{root_entry.snapshot.project.code}-{PurePosixPath(root_entry.path).stem}-with-references.zip",
    )


def viewer_file_format(filename, fallback=""):
    suffix = PurePosixPath(filename or "").suffix.lower()
    if suffix == ".stl":
        return "stl"
    if suffix == ".3mf":
        return "3mf"
    if fallback in {"stl", "3mf"}:
        return fallback
    return ""


def revision_viewer_artifact(revision):
    return revision.artifacts.filter(
        artifact_type=RevisionArtifact.ArtifactType.STL,
        view_name=VIEWER_PREVIEW_VIEW_NAME,
        metadata__preview_generator_version=PREVIEW_GENERATOR_VERSION,
    ).order_by("-created_at", "-id").first()


def viewer_file_response(field_file, filename, file_format):
    return FileResponse(
        field_file.open("rb"),
        as_attachment=False,
        filename=filename,
        content_type=VIEWER_CONTENT_TYPES.get(file_format, "application/octet-stream"),
    )


def missing_viewer_preview_response():
    return HttpResponseNotFound(
        "Fuer diese Datei gibt es noch keine 3D-Vorschau. Erzeuge zuerst die 3D-Vorschau."
    )


def viewer_status_payload(revision):
    artifact = revision_viewer_artifact(revision)
    if artifact:
        return {
            "status": "ready",
            "message": "3D-Vorschau ist bereit.",
            "source_url": reverse("plm:revision_viewer_source", args=[revision.id]),
        }

    pending_job = revision.export_jobs.filter(
        job_type=ExportJob.JobType.PNG_VIEWS,
        status__in=[ExportJob.Status.QUEUED, ExportJob.Status.RUNNING],
    ).order_by("-created_at").first()
    if pending_job:
        label = "laeuft" if pending_job.status == ExportJob.Status.RUNNING else "wartet"
        return {
            "status": pending_job.status,
            "message": f"3D-Vorschau {label}.",
            "job_id": pending_job.id,
        }

    failed_job = revision.export_jobs.filter(
        job_type=ExportJob.JobType.PNG_VIEWS,
        status=ExportJob.Status.FAILED,
    ).order_by("-created_at").first()
    if failed_job:
        return {
            "status": "failed",
            "message": failed_job.error or "3D-Vorschau konnte nicht erzeugt werden.",
            "job_id": failed_job.id,
        }

    return {
        "status": "missing",
        "message": "3D-Vorschau wird vorbereitet.",
    }


def revision_png_status_payload(revision):
    if revision_has_complete_png_views(revision):
        return {
            "status": "ready",
            "message": "PNG-Ansichten bereit.",
            "views_count": len(revision_png_view_names(revision)),
        }

    pending_job = (
        revision.export_jobs.filter(
            job_type=ExportJob.JobType.PNG_VIEWS,
            status__in=EXPORT_JOB_ACTIVE_STATUSES,
        )
        .order_by("-created_at")
        .first()
    )
    if pending_job:
        if pending_job.status == ExportJob.Status.RUNNING:
            message = "PNG-Ansichten werden erzeugt."
        else:
            message = "PNG-Ansichten sind eingeplant."
        return {
            "status": pending_job.status,
            "message": message,
            "job_id": pending_job.id,
        }

    failed_job = (
        revision.export_jobs.filter(
            job_type=ExportJob.JobType.PNG_VIEWS,
            status=ExportJob.Status.FAILED,
        )
        .order_by("-created_at")
        .first()
    )
    if failed_job:
        return {
            "status": "failed",
            "message": failed_job.error or "PNG-Ansichten konnten nicht erzeugt werden.",
            "job_id": failed_job.id,
        }

    return {
        "status": "missing",
        "message": "PNG-Ansichten fehlen noch.",
    }


def build_revision_compare_pairs(left_revision, right_revision):
    left_pngs = {
        artifact.view_name: artifact
        for artifact in left_revision.artifacts.filter(
            artifact_type=RevisionArtifact.ArtifactType.PNG,
            metadata__preview_generator_version=PREVIEW_GENERATOR_VERSION,
        )
    }
    right_pngs = {
        artifact.view_name: artifact
        for artifact in right_revision.artifacts.filter(
            artifact_type=RevisionArtifact.ArtifactType.PNG,
            metadata__preview_generator_version=PREVIEW_GENERATOR_VERSION,
        )
    }
    comparisons = []
    for view_name in sorted(set(left_pngs) & set(right_pngs)):
        comparisons.append(
            {
                "view_name": view_name,
                "left": left_pngs[view_name],
                "right": right_pngs[view_name],
            }
        )
    return comparisons


def revision_png_status_needs_poll(status_payload):
    return status_payload["status"] in {
        "queued",
        "running",
        "missing",
        "pending",
    }


def ensure_revision_viewer_preview(revision, user, *, process_inline=True):
    if revision_viewer_artifact(revision):
        return "ready"
    if revision_has_pending_png_job(revision):
        return "pending"

    job = create_export_job(
        revision=revision,
        job_type=ExportJob.JobType.PNG_VIEWS,
        created_by=user,
    )
    if process_inline and settings.PROCESS_EXPORT_JOBS_INLINE:
        process_export_job(job)
        job.refresh_from_db()
        revision.refresh_from_db()
        return "ready" if job.status == ExportJob.Status.SUCCEEDED and revision_viewer_artifact(revision) else "failed"
    return "queued"
