from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from django.core.exceptions import ValidationError


def read_uploaded_file(uploaded_file):
    position = uploaded_file.tell() if hasattr(uploaded_file, "tell") else None
    data = uploaded_file.read()
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(position or 0)
    return data


def validate_fcstd_upload(uploaded_file):
    filename = Path(uploaded_file.name).name
    if Path(filename).suffix.lower() != ".fcstd":
        raise ValidationError("Nur FreeCAD-Dateien mit der Endung .FCStd sind erlaubt.")

    data = read_uploaded_file(uploaded_file)
    if not data:
        raise ValidationError("Die FCStd-Datei ist leer.")

    try:
        with ZipFile(BytesIO(data)) as archive:
            members = archive.namelist()
    except BadZipFile as exc:
        raise ValidationError("Die FCStd-Datei muss ein gueltiges ZIP-Archiv sein.") from exc

    if not members:
        raise ValidationError("Die FCStd-Datei enthaelt keine Dateien.")

    member_names = set(members)
    return {
        "original_filename": filename,
        "size_bytes": len(data),
        "sha256": sha256(data).hexdigest(),
        "zip_member_count": len(members),
        "has_document_xml": "Document.xml" in member_names,
        "has_gui_document_xml": "GuiDocument.xml" in member_names,
    }
