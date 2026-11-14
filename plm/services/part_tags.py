"""Service layer for structured Part tags (AP-E2)."""
from hashlib import sha256 as _sha256

from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import PartTag


def tag_names(value):
    """Parse a comma-separated string or a list of raw strings into clean tag names.

    Normalisation rules:
    - Split on commas.
    - Strip Unicode whitespace from both ends of each segment.
    - Collapse internal runs of whitespace to a single space.
    - Discard empty segments and duplicates (case-insensitive via casefold).
    - The *first* occurrence of a casefolded name wins (preserves user capitalisation).
    - Commas within a single name are forbidden.
    - Maximum name length: 255 characters.
    - Maximum 100 tags per call.
    """
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ValidationError("Tags müssen als kommagetrennte Zeichenkette oder Liste angegeben werden.")
    seen = {}
    for raw in value:
        name = " ".join(raw.split())
        if not name:
            continue
        if len(name) > 255:
            raise ValidationError("Ein Tag darf höchstens 255 Zeichen enthalten.")
        key = name.casefold()
        seen.setdefault(key, name)
    if len(seen) > 100:
        raise ValidationError("Höchstens 100 Tags pro Teil sind erlaubt.")
    return list(seen.values())


@transaction.atomic
def set_part_tags(part, names):
    """Replace all tags on *part* with PartTag objects for *names*."""
    cleaned = tag_names(names)
    tags = []
    for name in cleaned:
        identity_hash = _sha256(name.casefold().encode("utf-8")).hexdigest()
        tag, _created = PartTag.objects.get_or_create(
            identity_hash=identity_hash,
            defaults={"name": name},
        )
        tags.append(tag)
    part.tags.set(tags)


def tags_as_legacy_string(part):
    """Return the tags of a Part as a canonical comma-separated string."""
    return ", ".join(part.tags.order_by("name", "pk").values_list("name", flat=True))
