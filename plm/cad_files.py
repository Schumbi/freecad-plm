import struct
from hashlib import sha256
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError

from .fcstd import (
    DEFAULT_PLM_MAX_FCSTD_UPLOAD_BYTES,
    read_uploaded_file,
    setting_int,
    validate_fcstd_upload,
    validate_uploaded_file_size,
)


CAD_FORMAT_FCSTD = "fcstd"
CAD_FORMAT_STEP = "step"
CAD_FORMAT_STL = "stl"

PROJECT_FILE_EXTENSIONS = {
    ".fcstd": CAD_FORMAT_FCSTD,
    ".step": CAD_FORMAT_STEP,
    ".stp": CAD_FORMAT_STEP,
    ".stl": CAD_FORMAT_STL,
}


def project_file_format(filename):
    suffix = PurePosixPath(filename or "").suffix.lower()
    try:
        return PROJECT_FILE_EXTENSIONS[suffix]
    except KeyError as exc:
        raise ValidationError(
            "Unterstützt werden FreeCAD-, STEP- und STL-Dateien "
            "(.FCStd, .step, .stp, .stl)."
        ) from exc


def validate_step_data(data):
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        try:
            text = data.decode("latin-1")
        except UnicodeDecodeError as exc:
            raise ValidationError("Die STEP-Datei ist nicht lesbar.") from exc
    normalized = text.upper()
    required_markers = ("ISO-10303-21;", "HEADER;", "DATA;", "END-ISO-10303-21;")
    if not all(marker in normalized for marker in required_markers):
        raise ValidationError("Die Datei enthält keine gültige STEP-Struktur.")


def validate_stl_data(data):
    if len(data) >= 84:
        triangle_count = struct.unpack_from("<I", data, 80)[0]
        if triangle_count > 0 and 84 + triangle_count * 50 == len(data):
            return

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("Die Datei enthält keine gültige STL-Struktur.") from exc
    vertices = 0
    facets = 0
    for line in text.splitlines():
        parts = line.strip().split()
        if parts and parts[0].lower() == "facet":
            facets += 1
        if len(parts) == 4 and parts[0].lower() == "vertex":
            try:
                float(parts[1])
                float(parts[2])
                float(parts[3])
            except ValueError as exc:
                raise ValidationError("Die STL-Datei enthält ungültige Koordinaten.") from exc
            vertices += 1
    if facets < 1 or vertices < 3 or vertices % 3:
        raise ValidationError("Die Datei enthält kein gültiges STL-Dreiecksnetz.")


def validate_project_file_upload(uploaded_file):
    file_format = project_file_format(uploaded_file.name)
    if file_format == CAD_FORMAT_FCSTD:
        metadata = validate_fcstd_upload(uploaded_file)
        return {**metadata, "file_format": file_format}

    max_upload_bytes = setting_int(
        "PLM_MAX_CAD_UPLOAD_BYTES",
        setting_int("PLM_MAX_FCSTD_UPLOAD_BYTES", DEFAULT_PLM_MAX_FCSTD_UPLOAD_BYTES),
    )
    validate_uploaded_file_size(uploaded_file, max_upload_bytes, "Die CAD-Datei")
    data = read_uploaded_file(uploaded_file)
    if not data:
        raise ValidationError("Die CAD-Datei ist leer.")
    if len(data) > max_upload_bytes:
        raise ValidationError("Die CAD-Datei ist größer als das erlaubte Upload-Budget.")

    if file_format == CAD_FORMAT_STEP:
        validate_step_data(data)
    else:
        validate_stl_data(data)

    return {
        "original_filename": PurePosixPath(uploaded_file.name).name,
        "size_bytes": len(data),
        "sha256": sha256(data).hexdigest(),
        "file_format": file_format,
    }
