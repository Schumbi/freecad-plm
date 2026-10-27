from django.conf import settings
from django.core import signing
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Prefetch
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from ..derivatives import prepare_revision_derivatives
from ..forms import ManufacturingFileUploadForm, PartForm, RevisionUploadForm
from ..freecadcmd import process_queued_export_jobs
from ..models import Annotation, AuditEvent, Checkout, ExportJob, Part, PrintProject, Project, ProjectSnapshotEntry, Revision, RevisionArtifact
from ..permissions import can_edit_revision_notes, can_release_revision, can_upload_revision, is_plm_admin
from ..services import (
    assembly_bom_tree,
    create_revision_from_upload,
    next_part_number,
    part_lifecycle_events,
)
from ..services.ux import reference_checkins_for_part
from ..services.snapshots import snapshot_entry_for_revision


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
    part = get_object_or_404(
        Part.objects.select_related("project", "family", "variant_source_revision__part"), id=part_id,
    )
    annotations = list(
        part.annotations.select_related("created_by", "revision").order_by(
            "status", "-created_at"
        )
    )
    revisions = (
        part.revisions.select_related("created_by")
        .prefetch_related(
            "artifacts",
            "export_jobs",
            "manufacturing_files",
            Prefetch(
                "primary_print_projects",
                queryset=PrintProject.objects.prefetch_related(
                    "sources", "plates", "snapshots"
                ),
            ),
        )
        .order_by("-created_at")
    )
    selected_revision = None
    selected_revision_id = request.GET.get("properties_revision")
    if selected_revision_id:
        selected_revision = revisions.filter(id=selected_revision_id).first()
    latest_revision = revisions.first()
    reference_checkins = reference_checkins_for_part(part)
    revisions = list(revisions)
    for revision in revisions:
        revision.reference_checkins = reference_checkins.get(revision.id, [])
        entry = snapshot_entry_for_revision(revision) if revision.file_format == Revision.FileFormat.FCSTD else None
        revision.import_dependencies = list(entry.snapshot.entries.filter(dependency_root_path=entry.path).select_related("revision__part").order_by("path")) if entry else []
    return render(
        request,
        "plm/part_detail.html",
        {
            "part": part,
            "variants": part.family.parts.filter(is_archived=False) if part.family_id else [],
            "annotations": annotations,
            "open_annotations_count": sum(
                annotation.status == Annotation.Status.OPEN
                for annotation in annotations
            ),
            "revisions": revisions,
            "selected_revision": selected_revision,
            "lifecycle_events": part_lifecycle_events(part),
            "bom_tree": (
                assembly_bom_tree(latest_revision)
                if part.category == Part.Category.ASSEMBLY
                else None
            ),
            "form": RevisionUploadForm(part=part),
            "manufacturing_form": ManufacturingFileUploadForm(),
            "can_upload": can_upload_revision(request.user),
            "can_manage_part": is_plm_admin(request.user),
            "can_release": can_release_revision(request.user),
            "can_delete_print_projects": can_release_revision(request.user),
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


@login_required
def remove_part(request, part_id):
    part = get_object_or_404(Part.objects.select_related("project"), pk=part_id)
    if not is_plm_admin(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Entfernen von Teilen.")
    archive = part.is_archived or not part.revisions.exists() or part.revisions.filter(file_format=Revision.FileFormat.FCSTD).exists()
    if request.method == "POST":
        if request.POST.get("confirmation", "").strip() != part.number:
            messages.error(request, "Die eingegebene Teilenummer stimmt nicht.")
        else:
            try:
                with transaction.atomic():
                    part = Part.objects.select_for_update().select_related("project").get(pk=part_id)
                    revisions = part.revisions.all()
                    archive = part.is_archived or not revisions.exists() or revisions.filter(file_format=Revision.FileFormat.FCSTD).exists()
                    expected_action = "restore" if part.is_archived else "archive" if archive else "delete"
                    if request.POST.get("action") != expected_action:
                        raise ValidationError("Die Dateisituation hat sich geändert. Bitte die Aktion erneut prüfen und bestätigen.")
                    if part.checkouts.filter(status=Checkout.Status.ACTIVE).exists():
                        raise ValidationError("Ein aktiver Checkout muss zuerst abgeschlossen oder abgebrochen werden.")
                    project_id, number = part.project_id, part.number
                    metadata = {"project_id": project_id, "part_id": part.id, "part_number": number}
                    label = str(part)
                    if archive:
                        restoring = part.is_archived
                        part.is_archived = not restoring
                        part.save(update_fields=["is_archived", "updated_at"])
                        action = AuditEvent.Action.PART_RESTORED if restoring else AuditEvent.Action.PART_ARCHIVED
                    else:
                        if ExportJob.objects.filter(revision__part=part, status__in=[ExportJob.Status.QUEUED, ExportJob.Status.RUNNING]).exists():
                            raise ValidationError("Laufende oder wartende Exportjobs müssen zuerst abgeschlossen werden.")
                        snapshot_entries = ProjectSnapshotEntry.objects.filter(revision__part=part).select_related("snapshot").order_by("id")
                        current_plan = {"part_id": part.id, "revisions": list(revisions.order_by("id").values_list("id", flat=True)), "entries": [list(row) for row in snapshot_entries.values_list("id", "snapshot_id", "path")]}
                        try:
                            confirmed_plan = signing.loads(request.POST.get("delete_plan", ""), salt="plm.remove_part", max_age=3600)
                        except signing.BadSignature:
                            raise ValidationError("Die Bestätigung ist abgelaufen. Bitte die betroffenen Projektstände erneut prüfen.")
                        if current_plan != confirmed_plan:
                            raise ValidationError("Die Revisionen oder Projektstände haben sich geändert. Bitte die Auswirkungen erneut prüfen.")
                        if Checkout.objects.filter(snapshot_id__in=snapshot_entries.values("snapshot_id"), status=Checkout.Status.ACTIVE).exists():
                            raise ValidationError("Ein betroffener Projektstand wird gerade in einem aktiven Checkout verwendet. Bitte den Checkout zuerst abschließen oder abbrechen.")
                        metadata["snapshot_entries"] = list(snapshot_entries.values("snapshot_id", "snapshot__name", "path"))
                        snapshot_entries.delete()
                        files = [(f.storage, f.name) for f in [*[r.file for r in revisions], *[a.file for a in RevisionArtifact.objects.filter(revision__part=part)]] if f and f.name]
                        part.annotations.all().delete()
                        RevisionArtifact.objects.filter(revision__part=part).delete()
                        ExportJob.objects.filter(revision__part=part).delete()
                        revisions.delete()
                        part.delete()
                        transaction.on_commit(lambda: [storage.delete(name) for storage, name in files])
                        action = AuditEvent.Action.PART_DELETED
                    AuditEvent.objects.create(actor=request.user, action=action, object_repr=label, metadata=metadata)
            except ProtectedError:
                messages.error(request, "Das Teil ist noch mit anderen Daten verknüpft (z. B. Projektständen, Checkouts, Varianten, Druckprojekten oder Fertigungsdaten) und kann nicht gelöscht werden.")
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            else:
                messages.success(request, f"{number} wurde {'wiederhergestellt' if action == AuditEvent.Action.PART_RESTORED else 'archiviert' if action == AuditEvent.Action.PART_ARCHIVED else 'dauerhaft gelöscht'}.")
                return redirect("plm:project_detail", project_id=project_id)
    snapshot_entries = list(ProjectSnapshotEntry.objects.filter(revision__part=part).select_related("snapshot").order_by("snapshot__name", "path")) if not archive else []
    delete_plan = signing.dumps({"part_id": part.id, "revisions": list(part.revisions.order_by("id").values_list("id", flat=True)), "entries": [[entry.id, entry.snapshot_id, entry.path] for entry in sorted(snapshot_entries, key=lambda item: item.id)]}, salt="plm.remove_part") if not archive else ""
    return render(request, "plm/part_confirm_remove.html", {"part": part, "archive": archive, "snapshot_entries": snapshot_entries, "delete_plan": delete_plan}, status=400 if request.method == "POST" else 200)
