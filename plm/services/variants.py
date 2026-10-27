"""Create independent CAD variants, including their parameter and linked files."""
from pathlib import PurePosixPath
from io import BytesIO
from posixpath import relpath
from uuid import uuid4
from xml.etree import ElementTree
from zipfile import ZipFile

from defusedxml.ElementTree import fromstring

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from ..models import AuditEvent, Part, PartFamily, Project, ProjectSnapshot, ProjectSnapshotEntry
from ..cad_files import validate_project_file_upload
from ..fcstd import read_uploaded_file, set_document_string_property
from .checkouts import create_checkout
from .manifests import manifest_entries_for_revision
from .revisions import create_revision_from_upload, next_part_number
from .snapshots import iter_project_zip_members, revision_reference_files, resolve_reference_path, snapshot_entry_for_revision


def independent_fcstd(data, path, paths):
    """Keep XLinks inside the variant instead of pointing at the source checkout."""
    target = BytesIO()
    with ZipFile(BytesIO(data)) as archive, ZipFile(target, "w") as output:
        for info in archive.infolist():
            content = archive.read(info)
            if info.filename == "Document.xml":
                root = fromstring(content)
                for link in root.findall(".//XLink"):
                    reference = link.get("file", "")
                    if not reference:
                        continue
                    resolved = resolve_reference_path(path, reference)
                    if resolved not in paths:
                        matches = [candidate for candidate in paths if PurePosixPath(candidate).name == PurePosixPath(reference.replace("\\", "/")).name]
                        if len(matches) != 1:
                            raise ValidationError("Die Variante enthält eine nicht eindeutig gespeicherte externe Referenz.")
                        resolved = matches[0]
                    link.set("file", relpath(resolved, str(PurePosixPath(path).parent)))
                # Chipbox BOM sheets also contain filenames as literal text cells.
                for cell in root.findall(".//Cell"):
                    value = cell.get("content", "")
                    reference = value.lstrip("'").replace("\\", "/")
                    if not reference.lower().endswith(".fcstd"):
                        continue
                    matches = [candidate for candidate in paths if PurePosixPath(candidate).name == PurePosixPath(reference).name]
                    if len(matches) == 1:
                        prefix = "'" if value.startswith("'") else ""
                        cell.set("content", prefix + relpath(matches[0], str(PurePosixPath(path).parent)))
                content = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
                content = set_document_string_property(content, "Id", str(uuid4()))
            output.writestr(info, content)
    return target.getvalue()


def create_variant_checkout(*, source_revision, uploaded_file, name, number, actor, snapshot=None, workspace_hint=""):
    if snapshot is None:
        source_root = snapshot_entry_for_revision(source_revision)
        snapshot = source_root.snapshot if source_root else None
    entries = manifest_entries_for_revision(source_revision, snapshot=snapshot)
    root = next(entry for entry in entries if entry["is_root"])
    if PurePosixPath(uploaded_file.name).suffix.lower() == ".zip":
        members = list(iter_project_zip_members(uploaded_file))
        contents = {member.path: member.data for member in members}
        if len(contents) != len(members):
            raise ValidationError("Doppelte Dateipfade im Variantenarchiv.")
        if set(contents) != {entry["path"] for entry in entries}:
            raise ValidationError("Das Variantenarchiv muss genau die Quelle und ihre Referenzdateien enthalten.")
    else:
        if len(entries) != 1:
            raise ValidationError("Diese Variante benötigt auch ihre verknüpften FreeCAD-Dateien als ZIP.")
        validate_project_file_upload(uploaded_file)
        contents = {root["path"]: read_uploaded_file(uploaded_file)}

    for path, data in contents.items():
        validate_project_file_upload(SimpleUploadedFile(PurePosixPath(path).name, data))
        if PurePosixPath(path).suffix.lower() == ".fcstd":
            contents[path] = independent_fcstd(data, path, set(contents))

    stored_files = []
    try:
        with transaction.atomic():
            project = Project.objects.select_for_update().get(pk=source_revision.part.project_id)
            variant_snapshot = ProjectSnapshot.objects.create(project=project, name=name, created_by=actor)
            root_revision = None
            for entry in sorted(entries, key=lambda item: not item["is_root"]):
                source_part = Part.objects.select_for_update().get(pk=entry["revision"].part_id)
                if source_part.is_archived:
                    raise ValidationError("Archivierte Quellen können nicht als Variante gespeichert werden.")
                family = source_part.family
                if family is None:
                    family = PartFamily.objects.create(project=project, name=source_part.name)
                    source_part.family = family
                    source_part.save(update_fields=["family", "updated_at"])
                part = Part.objects.create(
                    project=project, family=family, variant_source_revision=entry["revision"],
                    number=number if entry["is_root"] and number else next_part_number(project),
                    name=name if entry["is_root"] else f"{source_part.name} – {name}"[:200],
                    category=source_part.category,
                )
                part.full_clean()
                revision = create_revision_from_upload(
                    part=part,
                    uploaded_file=SimpleUploadedFile(PurePosixPath(entry["path"]).name, contents[entry["path"]]),
                    created_by=actor, normalize_plm_revision=True,
                    notes=f"Variante aus {source_part.number} {entry['revision'].revision_code}.",
                )
                stored_files.append((revision.file.storage, revision.file.name))
                source_entry = snapshot.entries.filter(path=entry["path"]).first() if snapshot else None
                ProjectSnapshotEntry.objects.create(snapshot=variant_snapshot, path=entry["path"], revision=revision, dependency_root_path=source_entry.dependency_root_path if source_entry else "")
                AuditEvent.objects.create(
                    actor=actor, action=AuditEvent.Action.PART_CREATED, object_repr=str(part),
                    metadata={"project_id": project.id, "part_id": part.id, "part_number": part.number,
                              "source": "addon_variant", "source_revision_id": entry["revision"].id,
                              "family_id": family.id, "snapshot_path": entry["path"]},
                )
                if entry["is_root"]:
                    root_revision = revision
            # Modified models may not introduce unsaved external dependencies.
            paths = set(contents)
            filenames = {PurePosixPath(path).name for path in paths}
            for snapshot_entry in variant_snapshot.entries.select_related("revision"):
                for reference in revision_reference_files(snapshot_entry.revision):
                    if resolve_reference_path(snapshot_entry.path, reference) not in paths and PurePosixPath(reference).name not in filenames:
                        raise ValidationError("Die Variante enthält eine nicht gespeicherte externe Referenz.")
            AuditEvent.objects.create(
                actor=actor, action=AuditEvent.Action.PROJECT_SNAPSHOT_CREATED,
                object_repr=str(variant_snapshot),
                metadata={"project_id": project.id, "snapshot_id": variant_snapshot.id,
                          "source_revision_id": source_revision.id, "entry_count": len(entries)},
            )
            checkout = create_checkout(root_revision, actor, snapshot=variant_snapshot, workspace_hint=workspace_hint)
            return root_revision.part, root_revision, checkout
    except Exception:
        for storage, filename in stored_files:
            storage.delete(filename)
        raise
