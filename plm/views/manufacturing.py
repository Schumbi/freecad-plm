from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from ..forms import ManufacturingFileUploadForm, RevisionUploadForm
from ..models import AuditEvent, ManufacturingFile, Revision
from ..permissions import can_edit_revision_notes, can_release_revision, can_upload_revision
from ..services import create_manufacturing_file_from_upload

from .common import (
    VIEWER_SUPPORTED_MANUFACTURING_TYPES,
    missing_viewer_preview_response,
    revision_viewer_artifact,
    viewer_file_format,
    viewer_file_response,
)


@login_required
def upload_manufacturing_file(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "part__project"),
        id=revision_id,
    )
    if not can_upload_revision(request.user):
        return HttpResponseForbidden(
            "Keine Berechtigung zum Hochladen von Fertigungsdateien."
        )
    if request.method != "POST":
        return redirect("plm:part_detail", part_id=revision.part_id)

    form = ManufacturingFileUploadForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            create_manufacturing_file_from_upload(
                revision=revision,
                uploaded_file=form.cleaned_data["file"],
                uploaded_by=request.user,
                file_type=form.cleaned_data.get("file_type", ""),
                purpose=form.cleaned_data["purpose"],
                status=ManufacturingFile.Status.APPROVED,
                label=form.cleaned_data["label"],
                description=form.cleaned_data["description"],
                slicer_name=form.cleaned_data["slicer_name"],
                slicer_version=form.cleaned_data["slicer_version"],
                machine=form.cleaned_data["machine"],
                machine_label=form.cleaned_data["machine_label"],
                printer_profile=form.cleaned_data["printer_profile"],
                material=form.cleaned_data["material"],
                material_brand=form.cleaned_data["material_brand"],
                nozzle_diameter=form.cleaned_data["nozzle_diameter"],
                layer_height=form.cleaned_data["layer_height"],
                estimated_print_time_seconds=form.cleaned_data[
                    "estimated_print_time_seconds"
                ],
                estimated_material_g=form.cleaned_data["estimated_material_g"],
            )
        except ValidationError as exc:
            form.add_error("file", exc)
        else:
            messages.success(
                request,
                f"Fertigungsdatei fuer {revision.revision_code} wurde hochgeladen.",
            )
            return redirect("plm:part_detail", part_id=revision.part_id)

    revisions = (
        revision.part.revisions.select_related("created_by")
        .prefetch_related("artifacts", "export_jobs", "manufacturing_files")
        .order_by("-created_at")
    )
    return render(
        request,
        "plm/part_detail.html",
        {
            "part": revision.part,
            "revisions": revisions,
            "selected_revision": revision,
            "form": RevisionUploadForm(),
            "manufacturing_form": form,
            "manufacturing_form_revision": revision,
            "can_upload": can_upload_revision(request.user),
            "can_release": can_release_revision(request.user),
            "can_edit_notes": can_edit_revision_notes(request.user),
        },
        status=400,
    )


@login_required
def download_manufacturing_file(request, manufacturing_file_id):
    manufacturing_file = get_object_or_404(
        ManufacturingFile.objects.select_related("revision", "revision__part"),
        id=manufacturing_file_id,
    )
    return FileResponse(
        manufacturing_file.file.open("rb"),
        as_attachment=True,
        filename=manufacturing_file.original_filename,
    )


@login_required
def manufacturing_file_viewer_source(request, manufacturing_file_id):
    manufacturing_file = get_object_or_404(
        ManufacturingFile.objects.select_related("revision", "revision__part"),
        id=manufacturing_file_id,
    )
    if manufacturing_file.file_type not in VIEWER_SUPPORTED_MANUFACTURING_TYPES:
        return HttpResponseForbidden(
            "Diese Fertigungsdatei kann nicht als 3D-Modell angezeigt werden."
        )

    file_format = viewer_file_format(manufacturing_file.original_filename)
    if file_format:
        return viewer_file_response(
            manufacturing_file.file,
            manufacturing_file.original_filename,
            file_format,
        )

    preview = revision_viewer_artifact(manufacturing_file.revision)
    if not preview:
        return missing_viewer_preview_response()
    return viewer_file_response(preview.file, preview.original_filename, "stl")


@login_required
def manufacturing_file_thumbnail(request, manufacturing_file_id):
    manufacturing_file = get_object_or_404(
        ManufacturingFile.objects.select_related("revision", "revision__part"),
        id=manufacturing_file_id,
    )
    if not manufacturing_file.thumbnail:
        return HttpResponseForbidden("Keine Vorschau fuer diese Fertigungsdatei.")
    return FileResponse(
        manufacturing_file.thumbnail.open("rb"),
        as_attachment=False,
        filename=manufacturing_file.thumbnail_original_filename or "preview.png",
    )


@login_required
def obsolete_manufacturing_file(request, manufacturing_file_id):
    manufacturing_file = get_object_or_404(
        ManufacturingFile.objects.select_related("revision", "revision__part"),
        id=manufacturing_file_id,
    )
    if not can_release_revision(request.user):
        return HttpResponseForbidden(
            "Keine Berechtigung zum Aendern von Fertigungsdatei-Status."
        )
    if request.method != "POST":
        return redirect("plm:part_detail", part_id=manufacturing_file.revision.part_id)

    old_status = manufacturing_file.status
    manufacturing_file.status = ManufacturingFile.Status.OBSOLETE
    manufacturing_file.save(update_fields=["status", "updated_at"])
    AuditEvent.objects.create(
        actor=request.user,
        action=AuditEvent.Action.MANUFACTURING_FILE_STATUS_CHANGED,
        object_repr=str(manufacturing_file),
        metadata={
            "manufacturing_file_id": manufacturing_file.id,
            "revision_id": manufacturing_file.revision_id,
            "old_status": old_status,
            "new_status": manufacturing_file.status,
        },
    )
    messages.success(request, "Fertigungsdatei wurde als obsolet markiert.")
    return redirect("plm:part_detail", part_id=manufacturing_file.revision.part_id)
