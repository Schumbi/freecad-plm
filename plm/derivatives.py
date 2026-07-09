from django.conf import settings

from .freecadcmd import PNG_VIEW_NAMES, create_export_job, process_export_job
from .models import ExportJob, RevisionArtifact

JOB_ACTIVE_STATUSES = (
    ExportJob.Status.QUEUED,
    ExportJob.Status.RUNNING,
)


def revision_png_view_names(revision):
    return set(
        revision.artifacts.filter(
            artifact_type=RevisionArtifact.ArtifactType.PNG,
            view_name__in=PNG_VIEW_NAMES,
        ).values_list("view_name", flat=True)
    )


def revision_has_complete_png_views(revision):
    return revision_png_view_names(revision) >= set(PNG_VIEW_NAMES)


def revision_has_pending_png_job(revision):
    return revision.export_jobs.filter(
        job_type=ExportJob.JobType.PNG_VIEWS,
        status__in=JOB_ACTIVE_STATUSES,
    ).exists()


def revision_has_freecadcmd_metadata(revision):
    return bool((revision.extracted_metadata or {}).get("freecadcmd"))


def revision_has_pending_inspect_job(revision):
    return revision.export_jobs.filter(
        job_type=ExportJob.JobType.INSPECT,
        status__in=JOB_ACTIVE_STATUSES,
    ).exists()


def ensure_revision_inspect_job(revision, user, *, process_inline=True):
    if revision_has_freecadcmd_metadata(revision):
        return "ready"
    if revision_has_pending_inspect_job(revision):
        return "pending"

    job = create_export_job(
        revision=revision,
        job_type=ExportJob.JobType.INSPECT,
        created_by=user,
    )
    if process_inline and settings.PROCESS_EXPORT_JOBS_INLINE:
        process_export_job(job)
        revision.refresh_from_db()
        job.refresh_from_db()
        return "ready" if job.status == ExportJob.Status.SUCCEEDED else "failed"
    return "queued"


def ensure_revision_png_views(revision, user, *, process_inline=True):
    if revision_has_complete_png_views(revision):
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
        return "ready" if job.status == ExportJob.Status.SUCCEEDED else "failed"
    return "queued"


def prepare_revision_derivatives(revisions, user):
    unique_revisions = {revision.id: revision for revision in revisions if revision}
    summary = {"created_jobs": 0, "ready": 0, "failed": 0, "pending": 0}
    for revision in unique_revisions.values():
        before_jobs = ExportJob.objects.filter(revision=revision).count()
        statuses = [
            ensure_revision_inspect_job(revision, user, process_inline=False),
            ensure_revision_png_views(revision, user, process_inline=False),
        ]
        after_jobs = ExportJob.objects.filter(revision=revision).count()
        summary["created_jobs"] += max(after_jobs - before_jobs, 0)
        summary["ready"] += statuses.count("ready")
        summary["failed"] += statuses.count("failed")
        summary["pending"] += statuses.count("pending") + statuses.count("queued")
    return summary
