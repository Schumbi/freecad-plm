from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from ..models import ExportJob

from .common import (
    EXPORT_JOB_ACTIVE_STATUSES,
)


EXPORT_JOB_RECENT_MINUTES = 5


def export_job_payload(job):
    revision = job.revision
    part = revision.part
    return {
        "id": job.id,
        "status": job.status,
        "job_type": job.job_type,
        "job_type_label": job.get_job_type_display(),
        "status_label": job.get_status_display(),
        "revision_id": revision.id,
        "revision_code": revision.revision_code,
        "part_id": part.id,
        "part_number": part.number,
        "project_code": part.project.code,
        "part_url": reverse("plm:part_detail", args=[part.id]),
        "error": job.error or "",
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@login_required
def user_export_jobs_status(request):
    recent_cutoff = timezone.now() - timedelta(minutes=EXPORT_JOB_RECENT_MINUTES)
    jobs = (
        ExportJob.objects.filter(created_by=request.user)
        .filter(
            Q(status__in=EXPORT_JOB_ACTIVE_STATUSES)
            | Q(finished_at__gte=recent_cutoff)
        )
        .select_related("revision", "revision__part", "revision__part__project")
        .order_by("-created_at")[:25]
    )
    active_count = ExportJob.objects.filter(
        created_by=request.user,
        status__in=EXPORT_JOB_ACTIVE_STATUSES,
    ).count()
    return JsonResponse(
        {
            "active_count": active_count,
            "poll": active_count > 0,
            "jobs": [export_job_payload(job) for job in jobs],
        }
    )
