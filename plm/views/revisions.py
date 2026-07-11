from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import FileResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from ..derivatives import ensure_revision_png_views, prepare_revision_derivatives
from ..forms import ManufacturingFileUploadForm, RevisionExportJobForm, RevisionNotesForm, RevisionUploadForm
from ..freecadcmd import create_export_job, process_export_job
from ..models import AuditEvent, ExportJob, Part, Revision, RevisionArtifact
from ..permissions import can_edit_revision_notes, can_release_revision, can_upload_revision
from ..services import PLMRevisionConflict, create_revision_from_upload, obsolete_revision, release_revision, revision_reference_files

from .common import (
    PENDING_REVISION_UPLOAD_SESSION_KEY,
    VIEWER_SUPPORTED_ARTIFACT_TYPES,
    build_revision_compare_pairs,
    clear_pending_revision_upload,
    ensure_revision_viewer_preview,
    missing_viewer_preview_response,
    referenced_revision_zip_response,
    revision_png_status_needs_poll,
    revision_png_status_payload,
    revision_viewer_artifact,
    save_pending_revision_upload,
    snapshot_entry_for_revision_download,
    viewer_file_format,
    viewer_file_response,
    viewer_status_payload,
)


@login_required
def revision_properties(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "part__project", "created_by"),
        id=revision_id,
    )
    return render(
        request,
        "plm/revision_properties.html",
        {
            "revision": revision,
        },
    )


@login_required
def upload_revision(request, part_id):
    part = get_object_or_404(Part.objects.select_related("project"), id=part_id)
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Hochladen von Revisionen.")

    if request.method != "POST":
        return redirect("plm:part_detail", part_id=part.id)

    form = RevisionUploadForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            revision = create_revision_from_upload(
                part=part,
                uploaded_file=form.cleaned_data["file"],
                created_by=request.user,
                notes=form.cleaned_data.get("change_summary", ""),
            )
        except PLMRevisionConflict as exc:
            pending = save_pending_revision_upload(
                part,
                form.cleaned_data["file"],
                exc,
                change_summary=form.cleaned_data.get("change_summary", ""),
            )
            request.session[PENDING_REVISION_UPLOAD_SESSION_KEY] = pending
            request.session.modified = True
            return render(
                request,
                "plm/revision_upload_conflict.html",
                {
                    "part": part,
                    "pending": pending,
                },
                status=409,
            )
        except ValidationError as exc:
            form.add_error("file", exc)
        else:
            derivative_summary = prepare_revision_derivatives([revision], request.user)
            messages.success(
                request,
                (
                    f"Revision {revision.revision_code} wurde hochgeladen. "
                    f"{derivative_summary['created_jobs']} Analyse-/PNG-Jobs vorbereitet."
                ),
            )
            return redirect("plm:part_detail", part_id=part.id)

    revisions = part.revisions.select_related("created_by").order_by("-created_at")
    return render(
        request,
        "plm/part_detail.html",
        {
            "part": part,
            "revisions": revisions,
            "form": form,
            "manufacturing_form": ManufacturingFileUploadForm(),
            "can_upload": can_upload_revision(request.user),
            "can_release": can_release_revision(request.user),
            "can_edit_notes": can_edit_revision_notes(request.user),
        },
        status=400,
    )


@login_required
def confirm_revision_upload(request, part_id):
    part = get_object_or_404(Part.objects.select_related("project"), id=part_id)
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Hochladen von Revisionen.")
    if request.method != "POST":
        return redirect("plm:part_detail", part_id=part.id)

    pending = request.session.get(PENDING_REVISION_UPLOAD_SESSION_KEY)
    if not pending or pending.get("part_id") != part.id:
        messages.error(request, "Es gibt keinen offenen Revisionsupload.")
        return redirect("plm:part_detail", part_id=part.id)

    action = request.POST.get("action")
    if action == "discard":
        clear_pending_revision_upload(request)
        messages.info(request, "Der Revisionsupload wurde verworfen.")
        return redirect("plm:part_detail", part_id=part.id)

    if action != "normalize":
        messages.error(request, "Unbekannte Upload-Aktion.")
        return redirect("plm:part_detail", part_id=part.id)

    try:
        with default_storage.open(pending["storage_name"], "rb") as source:
            uploaded_file = SimpleUploadedFile(
                pending["original_filename"],
                source.read(),
            )
        revision = create_revision_from_upload(
            part=part,
            uploaded_file=uploaded_file,
            created_by=request.user,
            normalize_plm_revision=True,
            notes=pending.get("change_summary", ""),
        )
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        derivative_summary = prepare_revision_derivatives([revision], request.user)
        messages.success(
            request,
            (
                f"Revision {revision.revision_code} wurde an das PLM angepasst und hochgeladen. "
                f"{derivative_summary['created_jobs']} Analyse-/PNG-Jobs vorbereitet."
            ),
        )
    finally:
        clear_pending_revision_upload(request)

    return redirect("plm:part_detail", part_id=part.id)


@login_required
def download_revision(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by"),
        id=revision_id,
    )
    snapshot_entry = snapshot_entry_for_revision_download(revision)
    references = revision_reference_files(revision)
    if references and not snapshot_entry:
        return HttpResponseForbidden(
            "Diese FCStd-Datei enthaelt Referenzen und kann nur mit den referenzierten Dateien heruntergeladen werden."
        )
    AuditEvent.objects.create(
        actor=request.user,
        action=AuditEvent.Action.REVISION_DOWNLOADED,
        object_repr=str(revision),
        metadata={
            "part_id": revision.part_id,
            "revision_id": revision.id,
            "revision_code": revision.revision_code,
            "sha256": revision.sha256,
            "original_filename": revision.original_filename,
            "download_mode": "referenced_zip" if snapshot_entry else "single_file",
            "snapshot_entry_id": snapshot_entry.id if snapshot_entry else None,
        },
    )
    if snapshot_entry:
        return referenced_revision_zip_response(snapshot_entry)
    return FileResponse(
        revision.file.open("rb"),
        as_attachment=True,
        filename=revision.original_filename,
    )


@login_required
def release_revision_view(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by"),
        id=revision_id,
    )
    if not can_release_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Freigeben von Revisionen.")
    if request.method != "POST":
        return redirect("plm:part_detail", part_id=revision.part_id)

    try:
        release_revision(revision, request.user)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(
            request,
            f"Revision {revision.revision_code} wurde freigegeben.",
        )
    return redirect("plm:part_detail", part_id=revision.part_id)


@login_required
def obsolete_revision_view(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by"),
        id=revision_id,
    )
    if not can_release_revision(request.user):
        return HttpResponseForbidden(
            "Keine Berechtigung zum Markieren von Revisionen als obsolet."
        )
    if request.method != "POST":
        return redirect("plm:part_detail", part_id=revision.part_id)

    try:
        obsolete_revision(revision, request.user)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(
            request,
            f"Revision {revision.revision_code} wurde als obsolet markiert.",
        )
    return redirect("plm:part_detail", part_id=revision.part_id)


@login_required
def update_revision_notes(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by"),
        id=revision_id,
    )
    if not can_edit_revision_notes(request.user):
        return HttpResponseForbidden(
            "Keine Berechtigung zum Bearbeiten von Revisionsnotizen."
        )
    if request.method != "POST":
        return redirect("plm:part_detail", part_id=revision.part_id)

    form = RevisionNotesForm(request.POST, instance=revision)
    if form.is_valid():
        form.save()
        AuditEvent.objects.create(
            actor=request.user,
            action=AuditEvent.Action.REVISION_NOTES_UPDATED,
            object_repr=str(revision),
            metadata={
                "part_id": revision.part_id,
                "revision_id": revision.id,
                "revision_code": revision.revision_code,
            },
        )
        messages.success(
            request,
            f"Anmerkungen fuer Revision {revision.revision_code} wurden gespeichert.",
        )
    return redirect("plm:part_detail", part_id=revision.part_id)


@login_required
def create_revision_inspect_job(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by"),
        id=revision_id,
    )
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Starten von FreeCAD-Jobs.")
    if request.method != "POST":
        return redirect("plm:part_detail", part_id=revision.part_id)

    create_export_job(
        revision=revision,
        job_type=ExportJob.JobType.INSPECT,
        created_by=request.user,
    )
    messages.success(
        request,
        f"FreeCAD-Analyse fuer {revision.revision_code} wurde eingeplant.",
    )
    return redirect("plm:part_detail", part_id=revision.part_id)


@login_required
def create_revision_png_job(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by"),
        id=revision_id,
    )
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Starten von FreeCAD-Jobs.")
    if request.method != "POST":
        return redirect("plm:part_detail", part_id=revision.part_id)

    job = create_export_job(
        revision=revision,
        job_type=ExportJob.JobType.PNG_VIEWS,
        created_by=request.user,
    )
    if settings.PROCESS_EXPORT_JOBS_INLINE:
        process_export_job(job)
        job.refresh_from_db()
        if job.status == ExportJob.Status.SUCCEEDED:
            messages.success(
                request,
                f"PNG-Ansichten fuer {revision.revision_code} wurden erzeugt.",
            )
        else:
            messages.error(
                request,
                f"PNG-Ansichten fuer {revision.revision_code} konnten nicht erzeugt werden.",
            )
    else:
        messages.success(
            request,
            f"PNG-Ansichten fuer {revision.revision_code} wurden eingeplant.",
        )
    return redirect("plm:part_detail", part_id=revision.part_id)


@login_required
def create_revision_viewer_preview(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by"),
        id=revision_id,
    )
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Erzeugen von 3D-Vorschauen.")
    if request.method != "POST":
        return redirect("plm:part_detail", part_id=revision.part_id)

    status = ensure_revision_viewer_preview(revision, request.user)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        revision.refresh_from_db()
        payload = viewer_status_payload(revision)
        if status == "failed":
            payload["status"] = "failed"
            payload.setdefault("message", f"3D-Vorschau fuer {revision.revision_code} konnte nicht erzeugt werden.")
        return JsonResponse(payload)

    if status == "ready":
        messages.success(request, f"3D-Vorschau fuer {revision.revision_code} ist verfuegbar.")
    elif status in {"queued", "pending"}:
        messages.info(
            request,
            "3D-Vorschau wurde eingeplant. Starte den Worker oder warte, bis er den Job verarbeitet hat.",
        )
    else:
        messages.error(request, f"3D-Vorschau fuer {revision.revision_code} konnte nicht erzeugt werden.")
    return redirect("plm:part_detail", part_id=revision.part_id)


@login_required
def revision_viewer_status(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by").prefetch_related("artifacts", "export_jobs"),
        id=revision_id,
    )
    return JsonResponse(viewer_status_payload(revision))


@login_required
def create_revision_export_job(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by"),
        id=revision_id,
    )
    if not can_upload_revision(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Starten von Exportjobs.")

    if request.method == "POST":
        form = RevisionExportJobForm(request.POST, revision=revision)
        if form.is_valid():
            create_export_job(
                revision=revision,
                job_type=ExportJob.JobType.EXPORT,
                export_format=form.cleaned_data["export_format"],
                selected_objects=form.cleaned_data["selected_objects"],
                created_by=request.user,
            )
            messages.success(
                request,
                f"Exportjob fuer {revision.revision_code} wurde eingeplant.",
            )
            return redirect("plm:part_detail", part_id=revision.part_id)
    else:
        form = RevisionExportJobForm(revision=revision)

    return render(
        request,
        "plm/revision_export_form.html",
        {
            "revision": revision,
            "form": form,
        },
        status=400 if request.method == "POST" else 200,
    )


@login_required
def download_revision_artifact(request, artifact_id):
    artifact = get_object_or_404(
        RevisionArtifact.objects.select_related("revision", "revision__part"),
        id=artifact_id,
    )
    as_attachment = request.GET.get("inline") != "1"
    return FileResponse(
        artifact.file.open("rb"),
        as_attachment=as_attachment,
        filename=artifact.original_filename,
    )


@login_required
def revision_viewer_source(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by").prefetch_related("artifacts"),
        id=revision_id,
    )
    artifact = revision_viewer_artifact(revision)
    if not artifact:
        return missing_viewer_preview_response()
    return viewer_file_response(artifact.file, artifact.original_filename, "stl")


@login_required
def artifact_viewer_source(request, artifact_id):
    artifact = get_object_or_404(
        RevisionArtifact.objects.select_related("revision", "revision__part"),
        id=artifact_id,
    )
    if artifact.artifact_type not in VIEWER_SUPPORTED_ARTIFACT_TYPES:
        return HttpResponseForbidden("Dieses Artefakt kann nicht als 3D-Modell angezeigt werden.")

    file_format = viewer_file_format(artifact.original_filename, artifact.artifact_type)
    if file_format:
        return viewer_file_response(artifact.file, artifact.original_filename, file_format)

    preview = revision_viewer_artifact(artifact.revision)
    if not preview:
        return missing_viewer_preview_response()
    return viewer_file_response(preview.file, preview.original_filename, "stl")


@login_required
def revision_compare(request, part_id):
    part = get_object_or_404(Part.objects.select_related("project"), id=part_id)
    revisions = (
        part.revisions.prefetch_related("artifacts", "export_jobs")
        .order_by("-created_at")
    )
    left_id = request.GET.get("left")
    right_id = request.GET.get("right")
    left_revision = revisions.filter(id=left_id).first() if left_id else None
    right_revision = revisions.filter(id=right_id).first() if right_id else None
    comparisons = []
    png_statuses = {}
    if left_revision and right_revision:
        if can_upload_revision(request.user):
            png_statuses[left_revision.id] = ensure_revision_png_views(
                left_revision,
                request.user,
            )
            png_statuses[right_revision.id] = ensure_revision_png_views(
                right_revision,
                request.user,
            )
            left_revision.refresh_from_db()
            right_revision.refresh_from_db()

        comparisons = build_revision_compare_pairs(left_revision, right_revision)
        if any(status in {"queued", "pending"} for status in png_statuses.values()):
            messages.info(
                request,
                "Fehlende PNG-Ansichten wurden eingeplant. Starte den Worker oder warte, bis er die Jobs verarbeitet hat.",
            )
        elif any(status == "failed" for status in png_statuses.values()):
            messages.error(
                request,
                "PNG-Ansichten konnten fuer mindestens eine Revision nicht erzeugt werden.",
            )

    compare_status_url = None
    if left_revision and right_revision:
        compare_status_url = (
            reverse("plm:revision_compare_status", args=[part.id])
            + f"?left={left_revision.id}&right={right_revision.id}"
        )

    return render(
        request,
        "plm/revision_compare.html",
        {
            "part": part,
            "revisions": revisions,
            "left_revision": left_revision,
            "right_revision": right_revision,
            "comparisons": comparisons,
            "png_statuses": png_statuses,
            "compare_status_url": compare_status_url,
        },
    )


@login_required
def revision_compare_status(request, part_id):
    part = get_object_or_404(Part.objects.select_related("project"), id=part_id)
    left_id = request.GET.get("left")
    right_id = request.GET.get("right")
    revisions = part.revisions.prefetch_related("artifacts", "export_jobs")
    left_revision = revisions.filter(id=left_id).first() if left_id else None
    right_revision = revisions.filter(id=right_id).first() if right_id else None

    if not left_revision or not right_revision:
        return JsonResponse(
            {
                "ready": False,
                "comparisons_count": 0,
                "revisions": {},
                "poll": False,
            }
        )

    comparisons = build_revision_compare_pairs(left_revision, right_revision)
    left_status = revision_png_status_payload(left_revision)
    right_status = revision_png_status_payload(right_revision)
    revisions_payload = {
        str(left_revision.id): {
            **left_status,
            "revision_code": left_revision.revision_code,
        },
        str(right_revision.id): {
            **right_status,
            "revision_code": right_revision.revision_code,
        },
    }
    poll = revision_png_status_needs_poll(left_status) or revision_png_status_needs_poll(
        right_status
    )
    return JsonResponse(
        {
            "ready": bool(comparisons),
            "comparisons_count": len(comparisons),
            "revisions": revisions_payload,
            "poll": poll,
        }
    )
