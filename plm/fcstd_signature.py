from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from django.core.exceptions import ValidationError


IGNORED_DOCUMENT_PROPERTIES = {
    "LastModifiedBy",
    "LastModifiedDate",
    "PLMRevision",
}
IGNORED_XML_ATTRIBUTES = {
    "Touched",
    "stamp",
    "status",
}
CHECKOUT_FILE_REFERENCE_RE = re.compile(
    r"(?P<prefix>'?)(?:[A-Za-z]:)?[/\\][^'\"<>]*[/\\]checkout-\d+[/\\]files[/\\]"
    r"(?P<filename>[^'\"<>]+?\.FCStd)",
    re.IGNORECASE,
)
FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?$")
SIGNATURE_RULES_VERSION = 2


def read_file_or_path(file_or_path):
    if isinstance(file_or_path, bytes):
        return file_or_path
    if isinstance(file_or_path, (str, Path)):
        return Path(file_or_path).read_bytes()

    was_closed = bool(getattr(file_or_path, "closed", False))
    if was_closed and hasattr(file_or_path, "open"):
        file_or_path.open("rb")
    position = file_or_path.tell() if hasattr(file_or_path, "tell") else None
    data = file_or_path.read()
    if hasattr(file_or_path, "seek"):
        file_or_path.seek(position or 0)
    if was_closed and hasattr(file_or_path, "close"):
        file_or_path.close()
    return data


def sort_attributes(element):
    if element.attrib:
        items = sorted(element.attrib.items())
        element.attrib.clear()
        element.attrib.update(items)
    for child in list(element):
        sort_attributes(child)


def normalize_whitespace(element):
    if element.text is not None:
        stripped = element.text.strip()
        element.text = stripped or None
    if element.tail is not None:
        stripped = element.tail.strip()
        element.tail = stripped or None
    for child in list(element):
        normalize_whitespace(child)


def remove_ignored_attributes(element):
    for name in IGNORED_XML_ATTRIBUTES:
        element.attrib.pop(name, None)
    for child in list(element):
        remove_ignored_attributes(child)


def remove_ignored_properties(root):
    properties_node = root.find("./Properties")
    if properties_node is None:
        return
    for property_node in list(properties_node.findall("./Property")):
        if property_node.attrib.get("name") in IGNORED_DOCUMENT_PROPERTIES:
            properties_node.remove(property_node)
    properties_node.attrib["Count"] = str(len(properties_node.findall("./Property")))


def normalize_checkout_file_references(value):
    return CHECKOUT_FILE_REFERENCE_RE.sub(
        lambda match: f"{match.group('prefix')}{match.group('filename')}",
        value,
    )


def normalize_attribute_value(value):
    value = normalize_checkout_file_references(value)
    if not FLOAT_RE.match(value):
        return value

    try:
        number = float(value)
    except ValueError:
        return value
    if abs(number) < 1e-9:
        return "0"
    return format(number, ".12g")


def normalize_attribute_values(element):
    for name, value in list(element.attrib.items()):
        element.attrib[name] = normalize_attribute_value(value)
    for child in list(element):
        normalize_attribute_values(child)


def normalized_document_xml(document_xml):
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as exc:
        raise ValidationError("Document.xml konnte nicht gelesen werden.") from exc

    remove_ignored_properties(root)
    remove_ignored_attributes(root)
    normalize_attribute_values(root)
    normalize_whitespace(root)
    sort_attributes(root)
    return ElementTree.tostring(root, encoding="utf-8")


def normalized_fcstd_document_xml(file_or_path):
    data = read_file_or_path(file_or_path)
    try:
        with ZipFile(BytesIO(data)) as archive:
            if "Document.xml" not in archive.namelist():
                raise ValidationError("Die FCStd-Datei enthaelt keine Document.xml.")
            return normalized_document_xml(archive.read("Document.xml"))
    except BadZipFile as exc:
        raise ValidationError("Die FCStd-Datei muss ein gueltiges ZIP-Archiv sein.") from exc


def fcstd_document_signature(file_or_path):
    return sha256(normalized_fcstd_document_xml(file_or_path)).hexdigest()


def fcstd_diagnostic_hashes(file_or_path):
    data = read_file_or_path(file_or_path)
    hashes = {}
    try:
        with ZipFile(BytesIO(data)) as archive:
            for name in sorted(archive.namelist()):
                if name.lower().endswith((".brp", ".brep")):
                    hashes[name] = sha256(archive.read(name)).hexdigest()
    except BadZipFile as exc:
        raise ValidationError("Die FCStd-Datei muss ein gueltiges ZIP-Archiv sein.") from exc
    return hashes


def fcstd_technical_signature(file_or_path):
    return {
        "rules_version": SIGNATURE_RULES_VERSION,
        "document_xml_sha256": fcstd_document_signature(file_or_path),
        "diagnostic_hashes": {
            "brep": fcstd_diagnostic_hashes(file_or_path),
        },
    }
