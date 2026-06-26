from hashlib import sha256
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from django.core.exceptions import ValidationError


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


def read_uploaded_file(uploaded_file):
    position = uploaded_file.tell() if hasattr(uploaded_file, "tell") else None
    data = uploaded_file.read()
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(position or 0)
    return data


def extract_document_xml_metadata(document_xml):
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError:
        return {}

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
        properties_node = ElementTree.SubElement(root, "Properties")

    property_node = None
    for candidate in properties_node.findall("./Property"):
        if candidate.attrib.get("name") == name:
            property_node = candidate
            break

    if property_node is None:
        property_node = ElementTree.SubElement(
            properties_node,
            "Property",
            {"name": name, "type": "App::PropertyString"},
        )
    else:
        property_node.attrib["type"] = "App::PropertyString"

    for child in list(property_node):
        property_node.remove(child)
    ElementTree.SubElement(property_node, "String", {"value": value})

    properties_node.attrib["Count"] = str(len(properties_node.findall("./Property")))
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


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
    except ElementTree.ParseError as exc:
        raise ValidationError("Document.xml konnte nicht gelesen werden.") from exc

    return target.getvalue()


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
            document_xml = (
                archive.read("Document.xml") if "Document.xml" in members else None
            )
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
        "freecad_document": (
            extract_document_xml_metadata(document_xml) if document_xml else {}
        ),
    }
