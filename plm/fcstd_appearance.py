"""Stable signatures for saved model appearance, excluding camera/UI state."""
from hashlib import sha256
import json
from defusedxml import ElementTree


APPEARANCE_PROPERTIES = {
    "ShapeColor", "ShapeAppearance", "DiffuseColor", "ShapeMaterial",
    "LineColor", "PointColor", "Transparency", "Visibility",
}


def fcstd_appearance_signature(archive):
    records = []
    if "GuiDocument.xml" in archive.namelist():
        root = ElementTree.fromstring(archive.read("GuiDocument.xml"))
        for provider in root.iter("ViewProvider"):
            for prop in provider.findall("./Properties/Property"):
                name = prop.get("name")
                if name not in APPEARANCE_PROPERTIES:
                    continue
                # Only semantic property data participates, not save flags,
                # provider ordering, ZIP timestamps or generated member names.
                prop.attrib = {"name": name}
                for node in prop.iter():
                    for flag in ("Touched", "status", "stamp"):
                        node.attrib.pop(flag, None)
                    member = node.get("file")
                    if member:
                        node.set("file", sha256(archive.read(member)).hexdigest())
                    node.attrib = dict(sorted(node.attrib.items()))
                    node.text = (node.text or "").strip() or None
                    node.tail = None
                records.append((provider.get("name", ""), name,
                                ElementTree.tostring(prop, encoding="unicode")))
    payload = json.dumps(sorted(records), ensure_ascii=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()
