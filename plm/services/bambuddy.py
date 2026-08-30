from dataclasses import asdict, dataclass
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from ..integrations.bambuddy import BambuddyClient, BambuddyProtocolError
from ..models import AuditEvent, ManufacturingFile


@dataclass
class BambuddySourceSyncResult:
    inspected: int = 0
    eligible: int = 0
    matched: int = 0
    uploaded: int = 0
    linked: int = 0
    already_attached: int = 0
    already_linked: int = 0
    skipped_status: int = 0
    skipped_printer: int = 0
    unmatched: int = 0
    ambiguous: int = 0

    def as_dict(self):
        return asdict(self)


def bambuddy_print_name(manufacturing_file):
    revision = manufacturing_file.revision
    return f"{revision.part.number}_{revision.revision_code}"


def plm_revision_url(revision):
    base_url = str(getattr(settings, "PLM_PUBLIC_URL", "") or "").strip()
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise BambuddyProtocolError(
            "PLM_PUBLIC_URL muss als vollständige HTTP- oder HTTPS-URL "
            "ohne Zugangsdaten, Query-String oder Fragment konfiguriert sein."
        )
    part_path = reverse("plm:part_detail", args=[revision.part_id]).lstrip("/")
    return f"{urljoin(f'{base_url.rstrip('/')}/', part_path)}#revision-{revision.id}"


def slicer_projects_by_print_name():
    projects = (
        ManufacturingFile.objects.filter(
            file_type=ManufacturingFile.FileType.SLICER_PROJECT_3MF,
        )
        .exclude(status=ManufacturingFile.Status.OBSOLETE)
        .select_related("revision__part", "uploaded_by")
        .order_by("id")
    )
    matches = {}
    for project in projects:
        matches.setdefault(bambuddy_print_name(project), []).append(project)
    return matches


def sync_bambuddy_source_projects(
    *,
    client=None,
    printer_ids=None,
    limit=20,
    dry_run=False,
):
    client = client or BambuddyClient.from_settings()
    printer_ids = set(
        settings.BAMBUDDY_SOURCE_SYNC_PRINTER_IDS
        if printer_ids is None
        else printer_ids
    )
    if not printer_ids:
        raise BambuddyProtocolError(
            "Für den Bambuddy-Source-Sync ist keine Drucker-ID konfiguriert."
        )

    archives = client.list_archives(limit=limit)
    projects_by_name = slicer_projects_by_print_name()
    result = BambuddySourceSyncResult(inspected=len(archives))

    for archive in archives:
        status = str(archive.get("status") or "").lower()
        if status not in {"printing", "completed"}:
            result.skipped_status += 1
            continue
        try:
            printer_id = int(archive.get("printer_id"))
            archive_id = int(archive.get("id"))
        except (TypeError, ValueError) as exc:
            raise BambuddyProtocolError(
                "Ein laufendes Bambuddy-Archiv enthält keine gültigen IDs."
            ) from exc
        if printer_id not in printer_ids:
            result.skipped_printer += 1
            continue

        source_attached = bool(archive.get("source_3mf_path"))
        revision_linked = bool(str(archive.get("external_url") or "").strip())
        if source_attached:
            result.already_attached += 1
        if revision_linked:
            result.already_linked += 1
        needs_source = status == "printing" and not source_attached
        needs_link = not revision_linked
        if not needs_source and not needs_link:
            continue

        result.eligible += 1
        print_name = str(archive.get("print_name") or "").strip()
        candidates = projects_by_name.get(print_name, [])
        if not candidates:
            result.unmatched += 1
            continue
        if len(candidates) != 1:
            result.ambiguous += 1
            continue

        project = candidates[0]
        result.matched += 1
        if dry_run:
            continue

        # Bambuddys Schreib-Endpunkte ersetzen vorhandene Werte. Daher direkt
        # vor dem Schreiben noch einmal das konkrete Archiv prüfen, um das
        # Zeitfenster zwischen Listenabfrage und Schreibzugriff klein zu halten.
        current_archive = client.get_archive(archive_id)
        current_status = str(current_archive.get("status") or "").lower()
        if current_status not in {"printing", "completed"}:
            result.skipped_status += 1
            continue

        current_external_url = str(current_archive.get("external_url") or "").strip()
        if current_external_url:
            if not revision_linked:
                result.already_linked += 1
        else:
            revision_url = plm_revision_url(project.revision)
            client.update_archive_external_url(archive_id, revision_url)
            link_history = list(
                (project.metadata or {}).get("bambuddy_revision_links", [])
            )
            link_history.append(
                {
                    "archive_id": archive_id,
                    "printer_id": printer_id,
                    "print_name": print_name,
                    "revision_url": revision_url,
                    "linked_at": timezone.now().isoformat(),
                }
            )
            project.metadata = {
                **(project.metadata or {}),
                "bambuddy_revision_links": link_history[-100:],
            }
            project.save(update_fields=["metadata", "updated_at"])
            AuditEvent.objects.create(
                actor=project.uploaded_by,
                action=AuditEvent.Action.BAMBUDDY_REVISION_LINKED,
                object_repr=str(project),
                metadata={
                    "manufacturing_file_id": project.id,
                    "revision_id": project.revision_id,
                    "bambuddy_archive_id": archive_id,
                    "bambuddy_printer_id": printer_id,
                    "print_name": print_name,
                    "revision_url": revision_url,
                },
            )
            result.linked += 1

        current_source_path = current_archive.get("source_3mf_path")
        if current_source_path:
            if not source_attached:
                result.already_attached += 1
        elif current_status == "printing":
            with project.file.open("rb") as source_file:
                response = client.upload_source_3mf(
                    archive_id,
                    source_file,
                    project.original_filename,
                )

            history = list(
                (project.metadata or {}).get("bambuddy_source_archives", [])
            )
            history.append({
                "archive_id": archive_id,
                "printer_id": printer_id,
                "print_name": print_name,
                "source_sha256": project.sha256,
                "attached_at": timezone.now().isoformat(),
            })
            project.metadata = {
                **(project.metadata or {}),
                "bambuddy_source_archives": history[-100:],
            }
            project.save(update_fields=["metadata", "updated_at"])
            AuditEvent.objects.create(
                actor=project.uploaded_by,
                action=AuditEvent.Action.BAMBUDDY_SOURCE_ATTACHED,
                object_repr=str(project),
                metadata={
                    "manufacturing_file_id": project.id,
                    "revision_id": project.revision_id,
                    "bambuddy_archive_id": archive_id,
                    "bambuddy_printer_id": printer_id,
                    "print_name": print_name,
                    "sha256": project.sha256,
                    "source_3mf_path": response.get("source_3mf_path", ""),
                },
            )
            result.uploaded += 1

    return result
