from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from ..derivatives import prepare_revision_derivatives
from ..models import AuditEvent, Checkout, CheckoutFileAddition
from .common import safe_snapshot_path, upload_file_digest
from .manifests import (
    manifest_entries_by_path,
    manifest_entries_for_checkout,
    manifest_entries_for_revision,
)
from .revisions import create_revision_from_upload, fcstd_model_changed
from .snapshots import (
    create_snapshot_from_checkout_revisions,
    snapshot_entry_for_revision,
)


@transaction.atomic
def create_checkout(base_revision, checked_out_by, snapshot=None, workspace_hint=""):
    part = base_revision.part
    if Checkout.objects.filter(part=part, status=Checkout.Status.ACTIVE).exists():
        raise ValidationError("Dieses Teil ist bereits ausgecheckt.")
    if snapshot is None:
        root_entry = snapshot_entry_for_revision(base_revision)
        if root_entry is not None:
            snapshot = root_entry.snapshot
    manifest_entries_for_revision(base_revision, snapshot=snapshot)
    checkout = Checkout.objects.create(
        part=part,
        base_revision=base_revision,
        snapshot=snapshot,
        checked_out_by=checked_out_by,
        workspace_hint=workspace_hint.strip(),
    )
    AuditEvent.objects.create(
        actor=checked_out_by,
        action=AuditEvent.Action.CHECKOUT_CREATED,
        object_repr=str(checkout),
        metadata={
            "checkout_id": checkout.id,
            "part_id": part.id,
            "base_revision_id": base_revision.id,
            "base_revision_code": base_revision.revision_code,
            "snapshot_id": snapshot.id if snapshot else None,
        },
    )
    return checkout


@transaction.atomic
def cancel_checkout(checkout, actor):
    if checkout.status != Checkout.Status.ACTIVE:
        raise ValidationError("Nur aktive Checkouts koennen abgebrochen werden.")
    checkout.status = Checkout.Status.CANCELED
    checkout.canceled_at = timezone.now()
    checkout.save(update_fields=["status", "canceled_at", "updated_at"])
    AuditEvent.objects.create(
        actor=actor,
        action=AuditEvent.Action.CHECKOUT_CANCELED,
        object_repr=str(checkout),
        metadata={
            "checkout_id": checkout.id,
            "part_id": checkout.part_id,
            "base_revision_id": checkout.base_revision_id,
        },
    )
    return checkout


@transaction.atomic
def add_checkout_file(checkout, revision, actor):
    if checkout.status != Checkout.Status.ACTIVE:
        raise ValidationError("Teile können nur zu aktiven Checkouts hinzugefügt werden.")
    if checkout.snapshot_id is None:
        raise ValidationError("Teile können nur zu Checkouts mit Projektstand hinzugefügt werden.")
    if revision.part.project_id != checkout.part.project_id:
        raise ValidationError("Das Teil gehört nicht zum Projekt des Checkouts.")
    if revision.part.is_archived:
        raise ValidationError("Archivierte Teile können nicht hinzugefügt werden.")
    if Checkout.objects.filter(
        part=revision.part,
        status=Checkout.Status.ACTIVE,
    ).exclude(id=checkout.id).exists():
        raise ValidationError("Das hinzuzufügende Teil ist bereits eigenständig ausgecheckt.")

    current_entries = manifest_entries_for_checkout(checkout)
    if any(entry["revision"].part_id == revision.part_id for entry in current_entries):
        raise ValidationError("Dieses Teil ist bereits im Checkout enthalten.")

    snapshot_entry = (
        checkout.snapshot.entries.filter(revision__part=revision.part)
        .select_related("revision")
        .order_by("path")
        .first()
    )
    if snapshot_entry is not None:
        path = safe_snapshot_path(snapshot_entry.path)
    else:
        root_entry = next(entry for entry in current_entries if entry["is_root"])
        root_dir = PurePosixPath(root_entry["path"]).parent
        filename = PurePosixPath(revision.original_filename).name
        path = safe_snapshot_path(str(root_dir / filename))

    if any(entry["path"] == path for entry in current_entries):
        raise ValidationError("Der Dateipfad ist bereits im Checkout enthalten.")

    addition = CheckoutFileAddition.objects.create(
        checkout=checkout,
        revision=revision,
        path=path,
    )
    AuditEvent.objects.create(
        actor=actor,
        action=AuditEvent.Action.CHECKOUT_FILE_ADDED,
        object_repr=str(checkout),
        metadata={
            "checkout_id": checkout.id,
            "part_id": revision.part_id,
            "revision_id": revision.id,
            "path": path,
        },
    )
    return addition


@transaction.atomic
def remove_checkout_file(checkout, path, actor):
    if checkout.status != Checkout.Status.ACTIVE:
        raise ValidationError("Nur aus aktiven Checkouts koennen Teile entfernt werden.")

    path = safe_snapshot_path(path.strip())
    entries_by_path = {
        entry["path"]: entry for entry in manifest_entries_for_checkout(checkout)
    }
    entry = entries_by_path.get(path)
    if entry is None:
        raise ValidationError("Dateipfad ist nicht Teil des Checkout-Manifests.")
    if entry["is_root"]:
        raise ValidationError("Das Hauptteil kann nicht aus dem Checkout entfernt werden.")

    addition = checkout.added_files.filter(path=path).first()
    canceled_addition = addition is not None
    if addition is not None:
        addition.delete()
    else:
        removed_paths = list(checkout.removed_paths or [])
        if path in removed_paths:
            raise ValidationError("Dieses Teil wurde bereits aus dem Checkout entfernt.")
        removed_paths.append(path)
        checkout.removed_paths = sorted(removed_paths)
        checkout.save(update_fields=["removed_paths", "updated_at"])

    AuditEvent.objects.create(
        actor=actor,
        action=AuditEvent.Action.CHECKOUT_FILE_REMOVED,
        object_repr=str(checkout),
        metadata={
            "checkout_id": checkout.id,
            "part_id": entry["revision"].part_id,
            "revision_id": entry["revision"].id,
            "path": path,
            "canceled_addition": canceled_addition,
        },
    )
    return entry


def complete_checkout(checkout, actor, completed_revision=None, revisions=None):
    revisions = revisions or []
    checkout.status = Checkout.Status.COMPLETED
    checkout.completed_revision = completed_revision
    checkout.completed_at = timezone.now()
    checkout.save(
        update_fields=[
            "status",
            "completed_revision",
            "completed_at",
            "updated_at",
        ]
    )
    completed_snapshot = create_snapshot_from_checkout_revisions(
        checkout,
        actor,
        revisions,
    )
    AuditEvent.objects.create(
        actor=actor,
        action=AuditEvent.Action.CHECKOUT_COMPLETED,
        object_repr=str(checkout),
        metadata={
            "checkout_id": checkout.id,
            "part_id": checkout.part_id,
            "base_revision_id": checkout.base_revision_id,
            "completed_revision_id": completed_revision.id if completed_revision else None,
            "completed_revision_code": (
                completed_revision.revision_code if completed_revision else ""
            ),
            "revisions": [
                {
                    "path": item["path"],
                    "revision_id": item["revision"].id,
                    "revision_code": item["revision"].revision_code,
                }
                for item in revisions
            ],
            "removed_paths": sorted(checkout.removed_paths or []),
            "added_paths": list(
                checkout.added_files.order_by("path").values_list("path", flat=True)
            ),
            "completed_snapshot_id": completed_snapshot.id if completed_snapshot else None,
        },
    )
    return checkout


@transaction.atomic
def checkin_checkout(checkout, uploaded_file, actor, notes=""):
    if checkout.status != Checkout.Status.ACTIVE:
        raise ValidationError("Nur aktive Checkouts koennen eingecheckt werden.")
    if not fcstd_model_changed(checkout.base_revision, uploaded_file):
        return {
            "root_revision": None,
            "revisions": [],
            "ignored_files": [
                {
                    "path": checkout.base_revision.original_filename,
                    "reason": "no_model_change",
                }
            ],
        }

    revision = create_revision_from_upload(
        part=checkout.part,
        uploaded_file=uploaded_file,
        created_by=actor,
        notes=notes,
    )
    complete_checkout(
        checkout,
        actor,
        completed_revision=revision,
        revisions=[
            {
                "path": checkout.base_revision.original_filename,
                "revision": revision,
            }
        ],
    )
    prepare_revision_derivatives([revision], actor)
    return {
        "root_revision": revision,
        "revisions": [
            {
                "path": checkout.base_revision.original_filename,
                "revision": revision,
                "is_root": True,
            }
        ],
        "ignored_files": [],
    }


@transaction.atomic
def checkin_checkout_files(checkout, files_metadata, uploaded_files, actor, notes=""):
    if checkout.status != Checkout.Status.ACTIVE:
        raise ValidationError("Nur aktive Checkouts koennen eingecheckt werden.")
    has_structural_changes = bool(checkout.removed_paths) or checkout.added_files.exists()
    if not files_metadata and not has_structural_changes:
        raise ValidationError("Keine Dateien fuer den Check-in angegeben.")

    manifest_by_path = manifest_entries_by_path(checkout)
    revisions = []
    ignored_files = []
    root_revision = None

    for item in files_metadata:
        if not isinstance(item, dict):
            raise ValidationError("files_metadata muss Objekte enthalten.")
        field = (item.get("field") or "").strip()
        path = safe_snapshot_path((item.get("path") or "").strip())
        if path not in manifest_by_path:
            raise ValidationError("Dateipfad ist nicht Teil des Checkout-Manifests.")

        manifest_entry = manifest_by_path[path]
        manifest_revision = manifest_entry["revision"]
        if item.get("revision_id") != manifest_revision.id:
            raise ValidationError("Revision passt nicht zum Checkout-Manifest.")
        if item.get("base_sha256") != manifest_revision.sha256:
            raise ValidationError("Basis-Hash passt nicht zum Checkout-Manifest.")
        if bool(item.get("is_root")) != bool(manifest_entry["is_root"]):
            raise ValidationError("Root-Markierung passt nicht zum Checkout-Manifest.")

        uploaded_file = uploaded_files.get(field)
        if uploaded_file is None:
            raise ValidationError("Upload-Datei fehlt fuer files_metadata.")
        uploaded_sha256, _size = upload_file_digest(uploaded_file)
        if item.get("sha256") and item["sha256"] != uploaded_sha256:
            raise ValidationError("Upload-Hash passt nicht zu files_metadata.")
        if not fcstd_model_changed(manifest_revision, uploaded_file):
            ignored_files.append(
                {
                    "path": path,
                    "reason": "no_model_change",
                }
            )
            continue

        revision = create_revision_from_upload(
            part=manifest_revision.part,
            uploaded_file=uploaded_file,
            created_by=actor,
            notes=notes,
        )
        revision_entry = {
            "path": path,
            "revision": revision,
            "is_root": manifest_entry["is_root"],
        }
        revisions.append(revision_entry)
        if manifest_entry["is_root"]:
            root_revision = revision

    if revisions or has_structural_changes:
        complete_checkout(
            checkout,
            actor,
            completed_revision=root_revision,
            revisions=revisions,
        )
        prepare_revision_derivatives(
            [entry["revision"] for entry in revisions],
            actor,
        )
    return {
        "root_revision": root_revision,
        "revisions": revisions,
        "ignored_files": ignored_files,
    }
