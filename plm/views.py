from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from .forms import RevisionUploadForm
from .models import AuditEvent, Part, Project, Revision
from .permissions import can_upload_revision
from .services import create_revision_from_upload


@login_required
def project_list(request):
    projects = Project.objects.filter(is_archived=False).order_by("code")
    return render(request, "plm/project_list.html", {"projects": projects})


@login_required
def project_detail(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    parts = project.parts.filter(is_archived=False).order_by("number")
    return render(
        request,
        "plm/project_detail.html",
        {
            "project": project,
            "parts": parts,
        },
    )


@login_required
def part_detail(request, part_id):
    part = get_object_or_404(Part.objects.select_related("project"), id=part_id)
    revisions = part.revisions.select_related("created_by").order_by("-created_at")
    return render(
        request,
        "plm/part_detail.html",
        {
            "part": part,
            "revisions": revisions,
            "form": RevisionUploadForm(),
            "can_upload": can_upload_revision(request.user),
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
            )
        except ValidationError as exc:
            form.add_error("file", exc)
        else:
            messages.success(
                request,
                f"Revision {revision.revision_code} wurde hochgeladen.",
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
            "can_upload": can_upload_revision(request.user),
        },
        status=400,
    )


@login_required
def download_revision(request, revision_id):
    revision = get_object_or_404(
        Revision.objects.select_related("part", "created_by"),
        id=revision_id,
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
        },
    )
    return FileResponse(
        revision.file.open("rb"),
        as_attachment=True,
        filename=revision.original_filename,
    )
