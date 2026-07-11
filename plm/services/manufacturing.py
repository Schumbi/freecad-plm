import json
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction

from ..fcstd import (
    DEFAULT_PLM_MAX_PROJECT_ZIP_BYTES,
    DEFAULT_PLM_MAX_ZIP_MEMBER_BYTES,
    DEFAULT_PLM_MAX_ZIP_MEMBERS,
    DEFAULT_PLM_MAX_ZIP_UNCOMPRESSED_BYTES,
    read_uploaded_file,
    setting_int,
    validate_uploaded_file_size,
    validate_zip_archive_budget,
)
from ..models import AuditEvent, ManufacturingFile
from .common import upload_file_digest


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

    if suffix == ".3mf":
        validate_uploaded_file_size(
            uploaded_file,
            setting_int(
                "PLM_MAX_PROJECT_ZIP_BYTES",
                DEFAULT_PLM_MAX_PROJECT_ZIP_BYTES,
            ),
            "Die 3MF-Datei",
        )
    file_sha256, size_bytes = upload_file_digest(uploaded_file)
    max_project_zip_bytes = setting_int(
        "PLM_MAX_PROJECT_ZIP_BYTES",
        DEFAULT_PLM_MAX_PROJECT_ZIP_BYTES,
    )
    metadata = {"extension": suffix}
    thumbnail = None
    if suffix == ".3mf":
        try:
            data = read_uploaded_file(uploaded_file)
            if len(data) > max_project_zip_bytes:
                raise ValidationError(
                    "Die 3MF-Datei ist groesser als das erlaubte Upload-Budget."
                )
            with ZipFile(BytesIO(data)) as archive:
                validate_zip_archive_budget(
                    archive,
                    label="Die 3MF-Datei",
                    max_members=setting_int(
                        "PLM_MAX_ZIP_MEMBERS",
                        DEFAULT_PLM_MAX_ZIP_MEMBERS,
                    ),
                    max_uncompressed_bytes=setting_int(
                        "PLM_MAX_ZIP_UNCOMPRESSED_BYTES",
                        DEFAULT_PLM_MAX_ZIP_UNCOMPRESSED_BYTES,
                    ),
                    max_member_bytes=setting_int(
                        "PLM_MAX_ZIP_MEMBER_BYTES",
                        DEFAULT_PLM_MAX_ZIP_MEMBER_BYTES,
                    ),
                )
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
