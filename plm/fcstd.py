from hashlib import sha256
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as StandardElementTree
from zipfile import BadZipFile, ZipFile

from django.conf import settings
from django.core.exceptions import ValidationError

from defusedxml import ElementTree

from .fcstd_signature import fcstd_technical_signature


FREECAD_STRING_PROPERTIES = (
    "Label",
    "Comment",
    "Company",
    "CreatedBy",
    "CreationDate",
    "Id",
    "LastModifiedBy",
    "LastModifiedDate",
    "License",
    "LicenseURL",
    "PLMRevision",
    "Uid",
)

PLM_REVISION_PROPERTY = "PLMRevision"
DEFAULT_PLM_MAX_FCSTD_UPLOAD_BYTES = 200 * 1024 * 1024
DEFAULT_PLM_MAX_PROJECT_ZIP_BYTES = 500 * 1024 * 1024
DEFAULT_PLM_MAX_ZIP_MEMBERS = 2000
DEFAULT_PLM_MAX_ZIP_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_PLM_MAX_ZIP_MEMBER_BYTES = 200 * 1024 * 1024
XML_SECURITY_ERRORS = (
    ElementTree.DTDForbidden,
    ElementTree.EntitiesForbidden,
    ElementTree.ExternalReferenceForbidden,
)
XML_PARSE_ERRORS = (ElementTree.ParseError,) + XML_SECURITY_ERRORS


def setting_int(name, default):
    return int(getattr(settings, name, default))


def validate_uploaded_file_size(uploaded_file, max_bytes, label):
    size = getattr(uploaded_file, "size", None)
    if size is not None and int(size) > max_bytes:
        raise ValidationError(f"{label} ist groesser als das erlaubte Upload-Budget.")


def validate_zip_archive_budget(
    archive,
    *,
    label,
    max_members,
    max_uncompressed_bytes,
    max_member_bytes,
):
    members = archive.infolist()
    if len(members) > max_members:
        raise ValidationError(f"{label} enthaelt zu viele ZIP-Mitglieder.")

    uncompressed_bytes = 0
    for info in members:
        if info.is_dir():
            continue
        if info.file_size > max_member_bytes:
            raise ValidationError(
                f"{label} enthaelt ein ZIP-Mitglied, das das Budget ueberschreitet."
            )
        uncompressed_bytes += info.file_size

    if uncompressed_bytes > max_uncompressed_bytes:
        raise ValidationError(
            f"{label} enthaelt zu viele unkomprimierte Daten."
        )


def read_uploaded_file(uploaded_file):
    was_closed = bool(getattr(uploaded_file, "closed", False))
    position = uploaded_file.tell() if hasattr(uploaded_file, "tell") else None
    data = uploaded_file.read()
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(position or 0)
    if was_closed and hasattr(uploaded_file, "close"):
        uploaded_file.close()
    return data


def extract_document_xml_metadata(document_xml):
    try:
        root = ElementTree.fromstring(document_xml)
    except XML_PARSE_ERRORS as exc:
        raise ValidationError("Document.xml konnte nicht gelesen werden.") from exc

    metadata = {
        "schema_version": root.attrib.get("SchemaVersion", ""),
        "program_version": root.attrib.get("ProgramVersion", ""),
        "file_version": root.attrib.get("FileVersion", ""),
        "document_kind": "part",
        "references": [],
        "properties": {},
    }

    object_types = [
        node.attrib.get("type", "") for node in root.findall("./Objects/Object")
    ]
    if any(object_type == "Assembly::AssemblyObject" for object_type in object_types):
        metadata["document_kind"] = "assembly"
    elif any(object_type == "App::VarSet" for object_type in object_types):
        metadata["document_kind"] = "parameters"

    references = []
    seen_references = set()
    for xlink in root.findall(".//XLink"):
        file_name = xlink.attrib.get("file")
        if not file_name or not file_name.lower().endswith(".fcstd"):
            continue
        reference = {
            "file": file_name,
            "name": xlink.attrib.get("name", ""),
            "sub": xlink.attrib.get("sub", ""),
        }
        key = tuple(reference.items())
        if key not in seen_references:
            references.append(reference)
            seen_references.add(key)
    metadata["references"] = references

    properties = metadata["properties"]
    for property_node in root.findall("./Properties/Property"):
        name = property_node.attrib.get("name")
        if name not in FREECAD_STRING_PROPERTIES:
            continue

        if name == "Uid":
            value_node = property_node.find("Uuid")
            value = value_node.attrib.get("value", "") if value_node is not None else ""
        else:
            value_node = property_node.find("String")
            value = value_node.attrib.get("value", "") if value_node is not None else ""

        properties[name] = value

    return metadata


def set_document_string_property(document_xml, name, value):
    root = ElementTree.fromstring(document_xml)
    properties_node = root.find("./Properties")
    if properties_node is None:
        properties_node = StandardElementTree.SubElement(root, "Properties")

    property_node = None
    for candidate in properties_node.findall("./Property"):
        if candidate.attrib.get("name") == name:
            property_node = candidate
            break

    if property_node is None:
        property_node = StandardElementTree.SubElement(
            properties_node,
            "Property",
            {"name": name, "type": "App::PropertyString"},
        )
    else:
        property_node.attrib["type"] = "App::PropertyString"

    for child in list(property_node):
        property_node.remove(child)
    StandardElementTree.SubElement(property_node, "String", {"value": value})

    properties_node.attrib["Count"] = str(len(properties_node.findall("./Property")))
    return StandardElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def fcstd_with_plm_revision(data, revision_code):
    source = BytesIO(data)
    target = BytesIO()
    try:
        with ZipFile(source) as archive:
            if "Document.xml" not in archive.namelist():
                raise ValidationError(
                    "Die FCStd-Datei enthaelt keine Document.xml fuer PLMRevision."
                )

            updated_document_xml = set_document_string_property(
                archive.read("Document.xml"),
                PLM_REVISION_PROPERTY,
                revision_code,
            )

            with ZipFile(target, "w") as updated_archive:
                for info in archive.infolist():
                    content = (
                        updated_document_xml
                        if info.filename == "Document.xml"
                        else archive.read(info.filename)
                    )
                    updated_archive.writestr(info, content)
    except BadZipFile as exc:
        raise ValidationError("Die FCStd-Datei muss ein gueltiges ZIP-Archiv sein.") from exc
    except XML_PARSE_ERRORS as exc:
        raise ValidationError("Document.xml konnte nicht gelesen werden.") from exc

    return target.getvalue()


def validate_fcstd_upload(uploaded_file):
    filename = Path(uploaded_file.name).name
    if Path(filename).suffix.lower() != ".fcstd":
        raise ValidationError("Nur FreeCAD-Dateien mit der Endung .FCStd sind erlaubt.")

    validate_uploaded_file_size(
        uploaded_file,
        setting_int("PLM_MAX_FCSTD_UPLOAD_BYTES", DEFAULT_PLM_MAX_FCSTD_UPLOAD_BYTES),
        "Die FCStd-Datei",
    )
    data = read_uploaded_file(uploaded_file)
    if not data:
        raise ValidationError("Die FCStd-Datei ist leer.")

    max_fcstd_upload_bytes = setting_int(
        "PLM_MAX_FCSTD_UPLOAD_BYTES",
        DEFAULT_PLM_MAX_FCSTD_UPLOAD_BYTES,
    )
    if len(data) > max_fcstd_upload_bytes:
        raise ValidationError("Die FCStd-Datei ist groesser als das erlaubte Upload-Budget.")

    try:
        with ZipFile(BytesIO(data)) as archive:
            validate_zip_archive_budget(
                archive,
                label="Die FCStd-Datei",
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
            members = archive.namelist()
            document_xml = (
                archive.read("Document.xml") if "Document.xml" in members else None
            )
    except BadZipFile as exc:
        raise ValidationError("Die FCStd-Datei muss ein gueltiges ZIP-Archiv sein.") from exc

    freecad_document = (
        extract_document_xml_metadata(document_xml) if document_xml else {}
    )

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
        "technical_signature": fcstd_technical_signature(data),
        "freecad_document": freecad_document,
    }
