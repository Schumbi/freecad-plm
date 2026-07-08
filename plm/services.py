import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import BytesIO
import json
from pathlib import PurePosixPath
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

from .fcstd import (
    PLM_REVISION_PROPERTY,
    fcstd_with_plm_revision,
    read_uploaded_file,
    validate_fcstd_upload,
)
from .models import (
    Annotation,
    AuditEvent,
    Checkout,
    ExportJob,
    ManufacturingFile,
    ManufacturingRun,
    ManufacturingRunAttachment,
    Part,
    ProjectSnapshot,
    ProjectSnapshotEntry,
    Revision,
    RevisionArtifact,
)


REVISION_CODE_PREFIX = "R"
REVISION_CODE_NUMBER_WIDTH = 4
REVISION_CODE_MAX_NUMBER = 10**REVISION_CODE_NUMBER_WIDTH - 1
REVISION_CODE_PATTERN = re.compile(
    rf"^{re.escape(REVISION_CODE_PREFIX)}(\d{{{REVISION_CODE_NUMBER_WIDTH}}})$"
)
MANUFACTURING_FILE_EXTENSIONS = {
    ".3mf": ManufacturingFile.FileType.SLICER_3MF,
    ".gcode": ManufacturingFile.FileType.GCODE,
    ".bgcode": ManufacturingFile.FileType.BGCODE,
    ".stl": ManufacturingFile.FileType.STL_PRINT,
    ".step": ManufacturingFile.FileType.STEP_VENDOR,
    ".stp": ManufacturingFile.FileType.STEP_VENDOR,
    ".pdf": ManufacturingFile.FileType.PDF_DRAWING,
}
BAMBU_CONFIG_NAMES = {
    "project_settings.config",
    "model_settings.config",
    "slice_info.config",
    "filament_settings.config",
    "printer_settings.config",
    "process_settings.config",
}
THREEMF_THUMBNAIL_PREFERRED_NAMES = (
    "Metadata/thumbnail.png",
    "Metadata/thumbnail1.png",
    "Metadata/plate_1_small.png",
    "Metadata/plate_1.png",
    "Metadata/top_1.png",
)


@dataclass(frozen=True)
class ProjectZipMember:
    path: str
    data: bytes


class PLMRevisionConflict(ValidationError):
    def __init__(self, *, expected, actual, original_filename, original_sha256):
        if actual:
            message = (
                f"{PLM_REVISION_PROPERTY} in der FCStd-Datei ist {actual}, "
                f"erwartet wird {expected}."
            )
        else:
            message = (
                f"{PLM_REVISION_PROPERTY} fehlt in der FCStd-Datei; "
                f"erwartet wird {expected}."
            )
        super().__init__(message)
        self.expected = expected
        self.actual = actual
        self.original_filename = original_filename
        self.original_sha256 = original_sha256


def upload_file_digest(uploaded_file):
    digest = sha256()
    size = 0
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
        size += len(chunk)
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    return digest.hexdigest(), size


def infer_manufacturing_file_type(filename):
    suffix = PurePosixPath(filename).suffix.lower()
    return MANUFACTURING_FILE_EXTENSIONS.get(suffix)


def decode_config_bytes(data):
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""


def flatten_config_value(value, prefix=""):
    if isinstance(value, dict):
        items = []
        for key, nested in value.items():
            key_prefix = f"{prefix}.{key}" if prefix else str(key)
            items.extend(flatten_config_value(nested, key_prefix).items())
        return dict(items)
    if isinstance(value, list):
        if all(not isinstance(item, (dict, list)) for item in value):
            return {prefix: ", ".join(unique_values(value))}
        items = {}
        for index, nested in enumerate(value):
            key_prefix = f"{prefix}.{index}" if prefix else str(index)
            items.update(flatten_config_value(nested, key_prefix))
        return items
    return {prefix: "" if value is None else str(value)}


def unique_values(values):
    unique = []
    seen = set()
    for value in values:
        if value in [None, ""]:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def parse_slicer_xml_config(stripped):
    parsed = {}
    try:
        root = ElementTree.fromstring(stripped)
    except ElementTree.ParseError:
        return parsed
    for node in root.iter():
        key = node.attrib.get("key")
        value = node.attrib.get("value")
        if key and value is not None:
            parsed[key] = value
    return parsed


def parse_slicer_config(text):
    parsed = {}
    stripped = text.strip()
    if not stripped:
        return parsed

    try:
        json_value = json.loads(stripped)
    except json.JSONDecodeError:
        json_value = None
    if json_value is not None:
        return flatten_config_value(json_value)

    xml_values = parse_slicer_xml_config(stripped)
    if xml_values:
        return xml_values

    for line in stripped.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";", "[")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip().strip('"')
    return parsed


def first_config_value(config, *keys):
    normalized = {key.lower(): value for key, value in config.items() if value}
    for key in keys:
        value = normalized.get(key.lower())
        if value:
            return value
    for wanted in keys:
        wanted = wanted.lower()
        for key, value in normalized.items():
            if key.endswith(f".{wanted}") or key.endswith(wanted):
                return value
    return ""


def decimal_config_value(config, *keys):
    value = first_config_value(config, *keys)
    if not value:
        return None
    value = str(value).split(",", 1)[0].strip()
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def int_config_value(config, *keys):
    value = first_config_value(config, *keys)
    if not value:
        return None
    value = str(value).split(",", 1)[0].strip()
    try:
        return int(float(value))
    except ValueError:
        return None


def json_safe_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: json_safe_value(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [json_safe_value(nested) for nested in value]
    return value


def slicer_config_priority(config_name):
    name = config_name.lower()
    path = PurePosixPath(name)
    if path.name.startswith("plate_") and path.suffix == ".json":
        return 10
    if path.name == "model_settings.config":
        return 20
    if path.name == "project_settings.config":
        return 30
    if path.name == "slice_info.config":
        return 40
    return 25


def extract_slicer_fields(configs):
    merged = {}
    source_names = []
    for item in sorted(configs, key=lambda item: slicer_config_priority(item["name"])):
        source_names.append(item["name"])
        merged.update(item["values"])

    machine_label = first_config_value(
        merged,
        "printer_model",
        "printer_model_id",
        "printer_name",
        "machine_name",
        "compatible_printers",
    )
    printer_profile = first_config_value(
        merged,
        "print_settings_id",
        "process_settings_id",
        "setting_id",
        "name",
        "inherits",
    )
    material = first_config_value(
        merged,
        "filament_type",
        "filament_settings_id",
        "filament_preset",
        "material_type",
    )
    material_brand = first_config_value(
        merged,
        "filament_vendor",
        "filament_brand",
        "material_brand",
    )
    slicer_name = first_config_value(merged, "slicer", "slicer_name")
    if not slicer_name:
        haystack = " ".join([*source_names, *merged.keys(), *merged.values()]).lower()
        if "bambu" in haystack or any(name.endswith(".config") for name in source_names):
            slicer_name = "Bambu Studio"

    return {
        "slicer_name": slicer_name,
        "slicer_version": first_config_value(
            merged,
        "slicer_version",
        "X-BBL-Client-Version",
        "bambu_studio_version",
        "version",
        ),
        "machine_label": machine_label,
        "printer_profile": printer_profile,
        "material": material,
        "material_brand": material_brand,
        "nozzle_diameter": decimal_config_value(
            merged,
            "nozzle_diameter",
            "nozzle_diameters",
            "printer_nozzle_diameter",
        ),
        "layer_height": decimal_config_value(merged, "layer_height"),
        "estimated_print_time_seconds": int_config_value(
            merged,
            "estimated_print_time",
            "print_time",
            "estimated_print_time_seconds",
        ),
        "estimated_material_g": decimal_config_value(
            merged,
            "filament_used_g",
            "total_filament_used_g",
            "estimated_material_g",
        ),
    }


def thumbnail_candidate_score(name):
    normalized = name.replace("\\", "/")
    if normalized in THREEMF_THUMBNAIL_PREFERRED_NAMES:
        return THREEMF_THUMBNAIL_PREFERRED_NAMES.index(normalized)
    lower_name = normalized.lower()
    if not lower_name.endswith((".png", ".jpg", ".jpeg")):
        return 1000
    if "thumbnail" in lower_name:
        return 100
    if "plate" in lower_name and "small" in lower_name:
        return 120
    if "plate" in lower_name:
        return 140
    if "top" in lower_name:
        return 160
    return 500


def select_3mf_thumbnail_name(names):
    candidates = [
        name
        for name in names
        if thumbnail_candidate_score(name) < 1000
    ]
    if not candidates:
        return ""
    return sorted(candidates, key=thumbnail_candidate_score)[0]


def inspect_manufacturing_upload(uploaded_file):
    original_filename = PurePosixPath(uploaded_file.name).name
    suffix = PurePosixPath(original_filename).suffix.lower()
    if suffix not in MANUFACTURING_FILE_EXTENSIONS:
        allowed = ", ".join(sorted(MANUFACTURING_FILE_EXTENSIONS))
        raise ValidationError(f"Nicht unterstuetzter Dateityp. Erlaubt: {allowed}.")

    file_sha256, size_bytes = upload_file_digest(uploaded_file)
    metadata = {"extension": suffix}
    thumbnail = None
    if suffix == ".3mf":
        try:
            data = read_uploaded_file(uploaded_file)
            with ZipFile(BytesIO(data)) as archive:
                names = archive.namelist()
                metadata["container"] = "3mf"
                metadata["members"] = [
                    {"name": name, "size": archive.getinfo(name).file_size}
                    for name in names[:200]
                ]
                metadata["has_thumbnail"] = any(
                    "thumbnail" in name.lower() for name in names
                )
                thumbnail_name = select_3mf_thumbnail_name(names)
                thumbnail = None
                if thumbnail_name:
                    thumbnail = {
                        "name": PurePosixPath(thumbnail_name).name,
                        "source": thumbnail_name,
                        "content": archive.read(thumbnail_name),
                    }
                    metadata["thumbnail"] = {
                        "name": thumbnail["name"],
                        "source": thumbnail["source"],
                        "size": len(thumbnail["content"]),
                    }
                configs = []
                for name in names:
                    path = PurePosixPath(name)
                    is_bambu_config = (
                        path.name in BAMBU_CONFIG_NAMES
                        or name.lower().endswith(".config")
                    )
                    is_plate_json = (
                        path.parent.name == "Metadata"
                        and path.name.startswith("plate_")
                        and path.suffix.lower() == ".json"
                    )
                    if not is_bambu_config and not is_plate_json:
                        continue
                    text = decode_config_bytes(archive.read(name))
                    values = parse_slicer_config(text)
                    if values:
                        configs.append({"name": name, "values": values})
                metadata["slicer_configs"] = [
                    {"name": item["name"], "keys": sorted(item["values"].keys())}
                    for item in configs
                ]
                metadata["extracted_fields"] = json_safe_value(
                    extract_slicer_fields(configs)
                )
        except BadZipFile as exc:
            raise ValidationError("3MF-Dateien muessen gueltige ZIP-Container sein.") from exc
    return {
        "original_filename": original_filename,
        "sha256": file_sha256,
        "size_bytes": size_bytes,
        "file_type": MANUFACTURING_FILE_EXTENSIONS[suffix],
        "metadata": metadata,
        "extracted_fields": metadata.get("extracted_fields", {}),
        "thumbnail": thumbnail if suffix == ".3mf" else None,
    }


@transaction.atomic
def create_manufacturing_file_from_upload(
    *,
    revision,
    uploaded_file,
    uploaded_by,
    file_type="",
    purpose=ManufacturingFile.Purpose.PRINT,
    status=ManufacturingFile.Status.APPROVED,
    label="",
    description="",
    slicer_name="",
    slicer_version="",
    machine=None,
    machine_label="",
    printer_profile="",
    material="",
    material_brand="",
    nozzle_diameter=None,
    layer_height=None,
    estimated_print_time_seconds=None,
    estimated_material_g=None,
):
    info = inspect_manufacturing_upload(uploaded_file)
    resolved_file_type = file_type or info["file_type"]
    extracted = info.get("extracted_fields", {})
    if ManufacturingFile.objects.filter(
        revision=revision,
        sha256=info["sha256"],
    ).exists():
        raise ValidationError(
            "Diese Fertigungsdatei ist fuer diese Revision bereits vorhanden."
        )

    manufacturing_file = ManufacturingFile.objects.create(
        revision=revision,
        file_type=resolved_file_type,
        purpose=purpose,
        status=status,
        file=uploaded_file,
        original_filename=info["original_filename"],
        sha256=info["sha256"],
        size_bytes=info["size_bytes"],
        label=label.strip(),
        description=description.strip(),
        slicer_name=slicer_name.strip() or extracted.get("slicer_name", ""),
        slicer_version=slicer_version.strip() or extracted.get("slicer_version", ""),
        machine=machine,
        machine_label=machine_label.strip() or extracted.get("machine_label", ""),
        printer_profile=printer_profile.strip() or extracted.get("printer_profile", ""),
        material=material.strip() or extracted.get("material", ""),
        material_brand=material_brand.strip() or extracted.get("material_brand", ""),
        nozzle_diameter=nozzle_diameter or extracted.get("nozzle_diameter"),
        layer_height=layer_height or extracted.get("layer_height"),
        estimated_print_time_seconds=(
            estimated_print_time_seconds
            or extracted.get("estimated_print_time_seconds")
        ),
        estimated_material_g=estimated_material_g or extracted.get("estimated_material_g"),
        metadata=info["metadata"],
        uploaded_by=uploaded_by,
    )
    thumbnail = info.get("thumbnail")
    if thumbnail:
        manufacturing_file.thumbnail.save(
            thumbnail["name"],
            ContentFile(thumbnail["content"]),
            save=False,
        )
        manufacturing_file.thumbnail_original_filename = thumbnail["name"]
        manufacturing_file.save(
            update_fields=[
                "thumbnail",
                "thumbnail_original_filename",
                "updated_at",
            ]
        )
    AuditEvent.objects.create(
        actor=uploaded_by,
        action=AuditEvent.Action.MANUFACTURING_FILE_UPLOADED,
        object_repr=str(manufacturing_file),
        metadata={
            "manufacturing_file_id": manufacturing_file.id,
            "revision_id": revision.id,
            "part_id": revision.part_id,
            "sha256": manufacturing_file.sha256,
            "file_type": manufacturing_file.file_type,
            "status": manufacturing_file.status,
            "machine_id": machine.id if machine else None,
        },
    )
    return manufacturing_file


def revision_code_number(code):
    match = REVISION_CODE_PATTERN.fullmatch(code or "")
    if not match:
        return None

    number = int(match.group(1))
    if number == 0:
        return None
    return number


def format_revision_code(number):
    if number < 1 or number > REVISION_CODE_MAX_NUMBER:
        highest_code = (
            f"{REVISION_CODE_PREFIX}"
            f"{REVISION_CODE_MAX_NUMBER:0{REVISION_CODE_NUMBER_WIDTH}d}"
        )
        raise ValidationError(
            f"Revisionscode muss zwischen {REVISION_CODE_PREFIX}0001 "
            f"und {highest_code} liegen."
        )
    return f"{REVISION_CODE_PREFIX}{number:0{REVISION_CODE_NUMBER_WIDTH}d}"


def next_revision_code(part):
    max_number = 0
    for code in part.revisions.values_list("revision_code", flat=True):
        number = revision_code_number(code)
        if number is not None:
            max_number = max(max_number, number)
    return format_revision_code(max_number + 1)


def revision_metadata_from_validation(metadata, plm_revision=None):
    extracted = {
        "zip_member_count": metadata["zip_member_count"],
        "has_document_xml": metadata["has_document_xml"],
        "has_gui_document_xml": metadata["has_gui_document_xml"],
        "technical_signature": metadata["technical_signature"],
        "freecad_document": metadata["freecad_document"],
    }
    if plm_revision:
        extracted["plm_revision"] = plm_revision
    return extracted


def revision_document_signature(revision):
    signature = (revision.extracted_metadata or {}).get("technical_signature", {})
    value = signature.get("document_xml_sha256")
    if not value:
        raise ValidationError("Basisrevision enthaelt keine technische FCStd-Signatur.")
    return value


def uploaded_document_signature(uploaded_file):
    metadata = validate_fcstd_upload(uploaded_file)
    return metadata["technical_signature"]["document_xml_sha256"]


def fcstd_model_changed(base_revision, uploaded_file):
    return revision_document_signature(base_revision) != uploaded_document_signature(
        uploaded_file
    )


def freecad_plm_revision(metadata):
    return (
        metadata.get("freecad_document", {})
        .get("properties", {})
        .get(PLM_REVISION_PROPERTY, "")
        .strip()
    )


def existing_revision_for_upload_hash(part, sha256):
    for revision in part.revisions.all():
        plm_revision = (revision.extracted_metadata or {}).get("plm_revision", {})
        if revision.sha256 == sha256 or plm_revision.get("original_upload_sha256") == sha256:
            return revision
    return None


def validate_revision_code_argument(revision_code):
    if revision_code is None:
        return None
    number = revision_code_number(revision_code)
    if number is None or format_revision_code(number) != revision_code:
        raise ValidationError("Manuelle Revisionscodes muessen das Format R0001 verwenden.")
    return revision_code


def next_part_number(project, category=Part.Category.PART):
    prefix = "A" if category == Part.Category.ASSEMBLY else "P"
    max_number = 0
    for number in project.parts.values_list("number", flat=True):
        if len(number) == 5 and number.startswith(f"{prefix}-") and number[2:].isdigit():
            max_number = max(max_number, int(number[2:]))
    return f"{prefix}-{max_number + 1:03d}"


def safe_snapshot_path(path):
    normalized = PurePosixPath(path)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValidationError("ZIP enthaelt einen unsicheren Dateipfad.")
    return str(normalized)


def part_category_from_metadata(metadata):
    document_kind = metadata.get("freecad_document", {}).get("document_kind")
    if document_kind == "assembly":
        return Part.Category.ASSEMBLY
    return Part.Category.PART


def part_identity_from_metadata(project, path, metadata):
    properties = metadata.get("freecad_document", {}).get("properties", {})
    category = part_category_from_metadata(metadata)
    freecad_id = (properties.get("Id") or "").strip()
    name = (properties.get("Label") or "").strip()
    if not name:
        name = PurePosixPath(path).stem

    if freecad_id:
        number = freecad_id
    else:
        existing_by_path = (
            ProjectSnapshotEntry.objects.filter(snapshot__project=project, path=path)
            .select_related("revision__part", "snapshot")
            .order_by("-snapshot__created_at", "-id")
            .first()
        )
        if existing_by_path:
            return existing_by_path.revision.part, False
        existing_by_name = project.parts.filter(name=name).order_by("id").first()
        if existing_by_name:
            return existing_by_name, False
        number = next_part_number(project, category)

    if project.parts.filter(number=number).exists():
        return project.parts.get(number=number), False

    part = Part.objects.create(
        project=project,
        number=number,
        name=name,
        category=category,
    )
    return part, True


def create_or_reuse_revision(part, path, data, created_by):
    upload = SimpleUploadedFile(PurePosixPath(path).name, data)
    metadata = validate_fcstd_upload(upload)
    existing = existing_revision_for_upload_hash(part, metadata["sha256"])
    if existing:
        return existing, False

    revision_code = next_revision_code(part)
    uploaded_plm_revision = freecad_plm_revision(metadata)
    original_sha256 = metadata["sha256"]
    normalized = uploaded_plm_revision != revision_code
    if normalized:
        data = fcstd_with_plm_revision(data, revision_code)
        metadata = validate_fcstd_upload(
            SimpleUploadedFile(PurePosixPath(path).name, data)
        )

    revision = Revision.objects.create(
        part=part,
        revision_code=revision_code,
        status=Revision.Status.DRAFT,
        file=ContentFile(data, name=PurePosixPath(path).name),
        original_filename=PurePosixPath(path).name,
        sha256=metadata["sha256"],
        size_bytes=metadata["size_bytes"],
        extracted_metadata=revision_metadata_from_validation(
            metadata,
            {
                "expected": revision_code,
                "uploaded": uploaded_plm_revision,
                "normalized": normalized,
                "original_upload_sha256": original_sha256,
                "stored_sha256": metadata["sha256"],
            },
        ),
        created_by=created_by,
    )
    return revision, True


def iter_fcstd_zip_members(uploaded_zip):
    data = read_uploaded_file(uploaded_zip)
    try:
        with ZipFile(BytesIO(data)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                path = safe_snapshot_path(info.filename)
                if not path.lower().endswith(".fcstd"):
                    continue
                yield ProjectZipMember(path=path, data=archive.read(info))
    except BadZipFile as exc:
        raise ValidationError("Die Projektdatei muss ein gueltiges ZIP-Archiv sein.") from exc


@transaction.atomic
def import_project_snapshot(project, uploaded_zip, created_by, name=""):
    members = list(iter_fcstd_zip_members(uploaded_zip))
    if not members:
        raise ValidationError("Das ZIP enthaelt keine FCStd-Dateien.")

    snapshot = ProjectSnapshot.objects.create(
        project=project,
        name=name.strip() or PurePosixPath(uploaded_zip.name).stem,
        created_by=created_by,
    )
    import_summary = {
        "created_parts": 0,
        "created_revisions": 0,
        "reused_revisions": 0,
        "files": [],
    }

    for member in members:
        metadata = validate_fcstd_upload(
            SimpleUploadedFile(PurePosixPath(member.path).name, member.data)
        )
        part, created_part = part_identity_from_metadata(project, member.path, metadata)
        if created_part:
            import_summary["created_parts"] += 1
        if created_part:
            AuditEvent.objects.create(
                actor=created_by,
                action=AuditEvent.Action.PART_CREATED,
                object_repr=str(part),
                metadata={
                    "project_id": project.id,
                    "part_id": part.id,
                    "part_number": part.number,
                    "category": part.category,
                    "snapshot_path": member.path,
                },
            )
        revision, created_revision = create_or_reuse_revision(
            part,
            member.path,
            member.data,
            created_by,
        )
        if created_revision:
            import_summary["created_revisions"] += 1
        else:
            import_summary["reused_revisions"] += 1
        import_summary["files"].append(
            {
                "path": member.path,
                "part_id": part.id,
                "part_number": part.number,
                "revision_id": revision.id,
                "revision_code": revision.revision_code,
                "created_part": created_part,
                "created_revision": created_revision,
            }
        )
        if created_revision:
            AuditEvent.objects.create(
                actor=created_by,
                action=AuditEvent.Action.REVISION_UPLOADED,
                object_repr=str(revision),
                metadata={
                    "part_id": part.id,
                    "revision_id": revision.id,
                    "revision_code": revision.revision_code,
                    "sha256": revision.sha256,
                    "original_filename": revision.original_filename,
                    "snapshot_path": member.path,
                    "plm_revision": revision.extracted_metadata.get("plm_revision", {}),
                },
            )
        ProjectSnapshotEntry.objects.create(
            snapshot=snapshot,
            path=member.path,
            revision=revision,
        )

    AuditEvent.objects.create(
        actor=created_by,
        action=AuditEvent.Action.PROJECT_SNAPSHOT_CREATED,
        object_repr=str(snapshot),
        metadata={
            "project_id": project.id,
            "snapshot_id": snapshot.id,
            "entry_count": snapshot.entries.count(),
            "import_summary": import_summary,
        },
    )
    snapshot.import_summary = import_summary
    return snapshot


@transaction.atomic
def delete_project_tree(project, actor):
    project = (
        type(project)
        .objects.select_for_update()
        .prefetch_related("parts__revisions__artifacts")
        .get(pk=project.pk)
    )
    summary = {
        "project_id": project.id,
        "project_code": project.code,
        "parts": project.parts.count(),
        "revisions": Revision.objects.filter(part__project=project).count(),
        "artifacts": RevisionArtifact.objects.filter(revision__part__project=project).count(),
        "manufacturing_files": ManufacturingFile.objects.filter(
            revision__part__project=project
        ).count(),
        "snapshots": project.snapshots.count(),
        "annotations": project.annotations.count(),
        "checkouts": Checkout.objects.filter(part__project=project).count(),
    }
    project_label = str(project)

    revisions = Revision.objects.filter(part__project=project)
    revision_files = [revision.file for revision in revisions if revision.file]
    artifact_files = [
        artifact.file
        for artifact in RevisionArtifact.objects.filter(revision__part__project=project)
        if artifact.file
    ]
    manufacturing_files = [
        item.file
        for item in ManufacturingFile.objects.filter(revision__part__project=project)
        if item.file
    ]
    manufacturing_thumbnails = [
        item.thumbnail
        for item in ManufacturingFile.objects.filter(revision__part__project=project)
        if item.thumbnail
    ]
    manufacturing_attachments = [
        item.file
        for item in ManufacturingRunAttachment.objects.filter(
            run__manufacturing_file__revision__part__project=project
        )
        if item.file
    ]

    AuditEvent.objects.create(
        actor=actor,
        action=AuditEvent.Action.PROJECT_DELETED,
        object_repr=project_label,
        metadata=summary,
    )

    Annotation.objects.filter(project=project).delete()
    Checkout.objects.filter(part__project=project).delete()
    ProjectSnapshotEntry.objects.filter(snapshot__project=project).delete()
    ProjectSnapshot.objects.filter(project=project).delete()
    ManufacturingRunAttachment.objects.filter(
        run__manufacturing_file__revision__part__project=project
    ).delete()
    ManufacturingRun.objects.filter(
        manufacturing_file__revision__part__project=project
    ).delete()
    ManufacturingFile.objects.filter(revision__part__project=project).delete()
    RevisionArtifact.objects.filter(revision__part__project=project).delete()
    ExportJob.objects.filter(revision__part__project=project).delete()
    revisions.delete()
    project.parts.all().delete()
    project.delete()

    for field_file in [
        *manufacturing_attachments,
        *manufacturing_thumbnails,
        *manufacturing_files,
        *artifact_files,
        *revision_files,
    ]:
        field_file.delete(save=False)

    return summary


def revision_reference_files(revision):
    document = (revision.extracted_metadata or {}).get("freecad_document", {})
    return [reference.get("file") for reference in document.get("references", []) if reference.get("file")]


def resolve_reference_path(source_path, reference_file):
    source_dir = PurePosixPath(source_path).parent
    if str(source_dir) == ".":
        return str(PurePosixPath(reference_file))
    return str(source_dir / reference_file)


def snapshot_entries_with_references(root_entry):
    entries_by_path = {
        entry.path: entry
        for entry in root_entry.snapshot.entries.select_related("revision", "revision__part")
    }
    entries_by_name = {
        PurePosixPath(entry.path).name: entry
        for entry in root_entry.snapshot.entries.select_related("revision", "revision__part")
    }
    selected = {}
    queue = [root_entry]

    while queue:
        entry = queue.pop(0)
        if entry.path in selected:
            continue
        selected[entry.path] = entry

        for reference_file in revision_reference_files(entry.revision):
            reference_path = resolve_reference_path(entry.path, reference_file)
            referenced_entry = entries_by_path.get(reference_path) or entries_by_name.get(
                PurePosixPath(reference_file).name
            )
            if referenced_entry and referenced_entry.path not in selected:
                queue.append(referenced_entry)

    return [selected[path] for path in sorted(selected)]


def snapshot_entry_for_revision(revision, snapshot=None):
    entries = revision.snapshot_entries.select_related(
        "snapshot",
        "snapshot__project",
        "revision",
        "revision__part",
    )
    if snapshot is not None:
        entries = entries.filter(snapshot=snapshot)
    return entries.order_by("-snapshot__created_at", "path").first()


def manifest_entries_for_revision(revision, snapshot=None):
    root_entry = snapshot_entry_for_revision(revision, snapshot=snapshot)
    references = revision_reference_files(revision)
    if references and root_entry is None:
        raise ValidationError(
            "Referenzierte Revisionen koennen nur mit Projektstand geladen werden."
        )
    if root_entry is None:
        return [
            {
                "path": safe_snapshot_path(revision.original_filename),
                "revision": revision,
                "is_root": True,
            }
        ]
    return [
        {
            "path": safe_snapshot_path(entry.path),
            "revision": entry.revision,
            "is_root": entry.id == root_entry.id,
        }
        for entry in snapshot_entries_with_references(root_entry)
    ]


def manifest_file_payload(entry):
    revision = entry["revision"]
    return {
        "path": entry["path"],
        "is_root": entry["is_root"],
        "revision_id": revision.id,
        "part_id": revision.part_id,
        "part_number": revision.part.number,
        "revision_code": revision.revision_code,
        "filename": revision.original_filename,
        "sha256": revision.sha256,
        "size_bytes": revision.size_bytes,
    }


def revision_manifest(revision, snapshot=None):
    entries = manifest_entries_for_revision(revision, snapshot=snapshot)
    return {
        "project": {
            "id": revision.part.project_id,
            "code": revision.part.project.code,
            "name": revision.part.project.name,
        },
        "part": {
            "id": revision.part_id,
            "number": revision.part.number,
            "name": revision.part.name,
            "category": revision.part.category,
        },
        "revision": {
            "id": revision.id,
            "revision_code": revision.revision_code,
            "status": revision.status,
            "original_filename": revision.original_filename,
            "sha256": revision.sha256,
            "size_bytes": revision.size_bytes,
        },
        "snapshot": (
            {
                "id": snapshot.id,
                "name": snapshot.name,
            }
            if snapshot is not None
            else None
        ),
        "files": [manifest_file_payload(entry) for entry in entries],
    }


def checkout_manifest(checkout):
    entries = manifest_entries_for_revision(
        checkout.base_revision,
        snapshot=checkout.snapshot,
    )
    return {
        "checkout_id": checkout.id,
        "status": checkout.status,
        "project": {
            "id": checkout.part.project_id,
            "code": checkout.part.project.code,
            "name": checkout.part.project.name,
        },
        "part": {
            "id": checkout.part_id,
            "number": checkout.part.number,
            "name": checkout.part.name,
            "category": checkout.part.category,
        },
        "base_revision": {
            "id": checkout.base_revision_id,
            "revision_code": checkout.base_revision.revision_code,
            "sha256": checkout.base_revision.sha256,
        },
        "snapshot": (
            {
                "id": checkout.snapshot_id,
                "name": checkout.snapshot.name,
            }
            if checkout.snapshot_id
            else None
        ),
        "files": [manifest_file_payload(entry) for entry in entries],
    }


def manifest_entries_by_path(checkout):
    return {
        entry["path"]: entry
        for entry in manifest_entries_for_revision(
            checkout.base_revision,
            snapshot=checkout.snapshot,
        )
    }


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
            "completed_snapshot_id": completed_snapshot.id if completed_snapshot else None,
        },
    )
    return checkout


def create_snapshot_from_checkout_revisions(checkout, actor, revisions):
    if not checkout.snapshot_id or not revisions:
        return None

    replacements = {item["path"]: item["revision"] for item in revisions}
    snapshot = ProjectSnapshot.objects.create(
        project=checkout.part.project,
        name=f"{checkout.snapshot.name} - Checkout {checkout.id}",
        created_by=actor,
    )
    for entry in checkout.snapshot.entries.select_related("revision").order_by("path"):
        ProjectSnapshotEntry.objects.create(
            snapshot=snapshot,
            path=entry.path,
            revision=replacements.get(entry.path, entry.revision),
        )
    AuditEvent.objects.create(
        actor=actor,
        action=AuditEvent.Action.PROJECT_SNAPSHOT_CREATED,
        object_repr=str(snapshot),
        metadata={
            "project_id": checkout.part.project_id,
            "snapshot_id": snapshot.id,
            "source_snapshot_id": checkout.snapshot_id,
            "checkout_id": checkout.id,
            "entry_count": snapshot.entries.count(),
            "updated_paths": sorted(replacements),
        },
    )
    return snapshot


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
    if not files_metadata:
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

    if revisions:
        complete_checkout(
            checkout,
            actor,
            completed_revision=root_revision,
            revisions=revisions,
        )
    return {
        "root_revision": root_revision,
        "revisions": revisions,
        "ignored_files": ignored_files,
    }


def create_annotation(
    *,
    part,
    created_by,
    text,
    revision=None,
    object_name="",
    subelement="",
):
    object_name = object_name.strip() if isinstance(object_name, str) else ""
    subelement = subelement.strip() if isinstance(subelement, str) else ""
    annotation = Annotation.objects.create(
        project=part.project,
        part=part,
        revision=revision,
        object_name=object_name,
        subelement=subelement,
        text=text.strip(),
        created_by=created_by,
    )
    AuditEvent.objects.create(
        actor=created_by,
        action=AuditEvent.Action.ANNOTATION_CREATED,
        object_repr=str(annotation),
        metadata={
            "annotation_id": annotation.id,
            "part_id": part.id,
            "revision_id": revision.id if revision else None,
            "object_name": annotation.object_name,
            "subelement": annotation.subelement,
        },
    )
    return annotation


@transaction.atomic
def create_revision_from_upload(
    part,
    uploaded_file,
    created_by,
    revision_code=None,
    normalize_plm_revision=False,
    notes="",
):
    metadata = validate_fcstd_upload(uploaded_file)
    file_data = read_uploaded_file(uploaded_file)
    code = validate_revision_code_argument(revision_code) or next_revision_code(part)
    uploaded_plm_revision = freecad_plm_revision(metadata)
    original_sha256 = metadata["sha256"]

    if existing_revision_for_upload_hash(part, original_sha256):
        raise ValidationError(
            "Diese FCStd-Datei wurde fuer dieses Teil bereits hochgeladen."
        )

    normalized = False
    if uploaded_plm_revision != code:
        if not normalize_plm_revision:
            raise PLMRevisionConflict(
                expected=code,
                actual=uploaded_plm_revision,
                original_filename=metadata["original_filename"],
                original_sha256=original_sha256,
            )
        file_data = fcstd_with_plm_revision(file_data, code)
        uploaded_file = ContentFile(file_data, name=metadata["original_filename"])
        metadata = validate_fcstd_upload(
            SimpleUploadedFile(metadata["original_filename"], file_data)
        )
        normalized = True

    if part.revisions.filter(sha256=metadata["sha256"]).exists():
        raise ValidationError(
            "Diese FCStd-Datei wurde fuer dieses Teil bereits hochgeladen."
        )

    revision = Revision.objects.create(
        part=part,
        revision_code=code,
        status=Revision.Status.DRAFT,
        file=uploaded_file,
        original_filename=metadata["original_filename"],
        sha256=metadata["sha256"],
        size_bytes=metadata["size_bytes"],
        notes=notes.strip(),
        extracted_metadata=revision_metadata_from_validation(
            metadata,
            {
                "expected": code,
                "uploaded": uploaded_plm_revision,
                "normalized": normalized,
                "original_upload_sha256": original_sha256,
                "stored_sha256": metadata["sha256"],
            },
        ),
        created_by=created_by,
    )

    if revision.size_bytes != len(file_data):
        raise ValueError("Stored revision size does not match uploaded data.")

    AuditEvent.objects.create(
        actor=created_by,
        action=AuditEvent.Action.REVISION_UPLOADED,
        object_repr=str(revision),
        metadata={
            "part_id": part.id,
            "revision_id": revision.id,
            "revision_code": revision.revision_code,
            "sha256": revision.sha256,
            "original_filename": revision.original_filename,
            "plm_revision": revision.extracted_metadata["plm_revision"],
            "change_summary": revision.notes,
        },
    )
    return revision


@transaction.atomic
def release_revision(revision, released_by):
    if revision.status == Revision.Status.RELEASED:
        raise ValidationError("Diese Revision ist bereits freigegeben.")
    if revision.status != Revision.Status.DRAFT:
        raise ValidationError("Nur Entwurfsrevisionen koennen freigegeben werden.")

    revision.status = Revision.Status.RELEASED
    revision.released_at = timezone.now()
    revision.save(update_fields=["status", "released_at", "updated_at"])

    AuditEvent.objects.create(
        actor=released_by,
        action=AuditEvent.Action.REVISION_RELEASED,
        object_repr=str(revision),
        metadata={
            "part_id": revision.part_id,
            "revision_id": revision.id,
            "revision_code": revision.revision_code,
            "sha256": revision.sha256,
            "original_filename": revision.original_filename,
        },
    )
    return revision
