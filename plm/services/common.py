from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError

from ..fcstd import PLM_REVISION_PROPERTY


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


def safe_snapshot_path(path):
    normalized = PurePosixPath(path)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValidationError("ZIP enthaelt einen unsicheren Dateipfad.")
    return str(normalized)
