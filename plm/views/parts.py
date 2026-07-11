from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from ..derivatives import prepare_revision_derivatives
from ..forms import ManufacturingFileUploadForm, PartForm, RevisionUploadForm
from ..freecadcmd import process_queued_export_jobs
from ..models import AuditEvent, ExportJob, Part, Project
from ..permissions import can_edit_revision_notes, can_release_revision, can_upload_revision
from ..services import create_revision_from_upload, next_part_number


@login_required
def create_part(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Anlegen von Teilen.")

    if request.method == "POST":
        form = PartForm(request.POST, request.FILES, project=project)
        if form.is_valid():
            revision = None
            try:
                with transaction.atomic():
                    part = form.save(commit=False)
                    part.project = project
                    if not part.number:
                        part.number = next_part_number(project)
                    part.save()
                    AuditEvent.objects.create(
                        actor=request.user,
                        action=AuditEvent.Action.PART_CREATED,
                        object_repr=str(part),
                        metadata={
                            "project_id": project.id,
                            "part_id": part.id,
                            "part_number": part.number,
                            "category": part.category,
                        },
                    )
                    revision = create_revision_from_upload(
                        part=part,
                        uploaded_file=form.cleaned_data["file"],
                        created_by=request.user,
                        normalize_plm_revision=True,
                        notes=form.cleaned_data.get("change_summary", ""),
                    )
            except ValidationError as exc:
                form.add_error("file", exc)
            else:
                derivative_summary = prepare_revision_derivatives([revision], request.user)
                messages.success(
                    request,
                    (
                        f"{part.number} wurde mit initialer Revision angelegt. "
                        f"{derivative_summary['created_jobs']} Analyse-/PNG-Jobs vorbereitet."
                    ),
                )
                return redirect("plm:part_detail", part_id=part.id)
    else:
        form = PartForm(project=project)

    return render(
        request,
        "plm/part_form.html",
        {
            "project": project,
            "form": form,
        },
        status=400 if request.method == "POST" else 200,
    )


@login_required
def part_detail(request, part_id):
    part = get_object_or_404(Part.objects.select_related("project"), id=part_id)
    revisions = (
        part.revisions.select_related("created_by")
        .prefetch_related("artifacts", "export_jobs", "manufacturing_files")
        .order_by("-created_at")
    )
    selected_revision = None
    selected_revision_id = request.GET.get("properties_revision")
    if selected_revision_id:
        selected_revision = revisions.filter(id=selected_revision_id).first()
    return render(
        request,
        "plm/part_detail.html",
        {
            "part": part,
            "revisions": revisions,
            "selected_revision": selected_revision,
            "form": RevisionUploadForm(),
            "manufacturing_form": ManufacturingFileUploadForm(),
            "can_upload": can_upload_revision(request.user),
            "can_release": can_release_revision(request.user),
            "can_edit_notes": can_edit_revision_notes(request.user),
        },
    )


@login_required
def part_properties(request, part_id):
    part = get_object_or_404(Part.objects.select_related("project"), id=part_id)
    return render(
        request,
        "plm/part_properties.html",
        {
            "part": part,
        },
    )


@login_required
def process_export_jobs_once(request, part_id):
    part = get_object_or_404(Part, id=part_id)
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Starten von FreeCAD-Jobs.")
    if request.method != "POST":
        return redirect("plm:part_detail", part_id=part.id)
    if not settings.PROCESS_EXPORT_JOBS_INLINE:
        messages.info(
            request,
            "Wartende Jobs werden vom Worker im Hintergrund verarbeitet.",
        )
        return redirect("plm:part_detail", part_id=part.id)

    jobs = process_queued_export_jobs()
    succeeded = sum(1 for job in jobs if job.status == ExportJob.Status.SUCCEEDED)
    failed = sum(1 for job in jobs if job.status == ExportJob.Status.FAILED)
    if jobs:
        messages.success(
            request,
            f"{len(jobs)} Job(s) verarbeitet: {succeeded} erfolgreich, {failed} fehlgeschlagen.",
        )
    else:
        messages.info(request, "Keine wartenden Jobs vorhanden.")
    return redirect("plm:part_detail", part_id=part.id)
