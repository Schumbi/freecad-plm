import json
import ssl
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from django.conf import settings


MAX_JSON_RESPONSE_BYTES = 1024 * 1024


class BambuddyError(Exception):
    """Base class for Bambuddy integration failures safe to show to an admin."""


class BambuddyConfigurationError(BambuddyError):
    pass


class BambuddyAuthenticationError(BambuddyError):
    pass


class BambuddyConnectionError(BambuddyError):
    pass


class BambuddyProtocolError(BambuddyError):
    pass


@dataclass(frozen=True)
class BambuddyConnectionInfo:
    total_archives: int | None
    returned_archives: int


def validate_bambuddy_url(value):
    url = str(value or "").strip().rstrip("/")
    if not url:
        raise BambuddyConfigurationError("BAMBUDDY_URL ist nicht konfiguriert.")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BambuddyConfigurationError(
            "BAMBUDDY_URL muss eine vollständige HTTP- oder HTTPS-URL sein."
        )
    if parsed.username or parsed.password:
        raise BambuddyConfigurationError(
            "Zugangsdaten dürfen nicht Bestandteil von BAMBUDDY_URL sein."
        )
    if parsed.query or parsed.fragment:
        raise BambuddyConfigurationError(
            "BAMBUDDY_URL darf keinen Query-String oder Fragmentteil enthalten."
        )
    return url


class BambuddyClient:
    def __init__(self, base_url, api_key, timeout_seconds=10, opener=urlopen):
        self.base_url = validate_bambuddy_url(base_url)
        self.api_key = str(api_key or "").strip()
        if not self.api_key:
            raise BambuddyConfigurationError(
                "BAMBUDDY_API_KEY ist nicht konfiguriert."
            )
        try:
            self.timeout_seconds = int(timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise BambuddyConfigurationError(
                "BAMBUDDY_TIMEOUT_SECONDS muss eine ganze Zahl sein."
            ) from exc
        if not 1 <= self.timeout_seconds <= 60:
            raise BambuddyConfigurationError(
                "BAMBUDDY_TIMEOUT_SECONDS muss zwischen 1 und 60 liegen."
            )
        self.opener = opener

    @classmethod
    def from_settings(cls):
        return cls(
            settings.BAMBUDDY_URL,
            settings.BAMBUDDY_API_KEY,
            settings.BAMBUDDY_TIMEOUT_SECONDS,
        )

    def api_url(self, path, query=None):
        base = self.base_url
        if base.endswith("/api/v1"):
            base = base[: -len("/api/v1")]
        url = f"{base}/api/v1/{str(path).lstrip('/')}"
        if query:
            url = f"{url}?{urlencode(query)}"
        return url

    def get_json(self, path, query=None):
        request = Request(
            self.api_url(path, query),
            headers={
                "Accept": "application/json",
                "User-Agent": "FreeCAD-PLM Bambuddy integration",
                "X-API-Key": self.api_key,
            },
            method="GET",
        )
        try:
            with self.opener(
                request,
                timeout=self.timeout_seconds,
                context=ssl.create_default_context(),
            ) as response:
                content = response.read(MAX_JSON_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise BambuddyAuthenticationError(
                    "Bambuddy hat den API-Key abgelehnt. Benötigt wird mindestens „Read Status“."
                ) from exc
            raise BambuddyConnectionError(
                f"Bambuddy antwortete mit HTTP {exc.code}."
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise BambuddyConnectionError(
                f"Bambuddy ist nicht erreichbar: {exc}"
            ) from exc
        if len(content) > MAX_JSON_RESPONSE_BYTES:
            raise BambuddyProtocolError("Die Bambuddy-Antwort ist unerwartet groß.")
        try:
            return json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BambuddyProtocolError(
                "Bambuddy lieferte keine gültige JSON-Antwort."
            ) from exc

    def test_connection(self):
        payload = self.get_json("archives/", {"limit": 1, "offset": 0})
        if isinstance(payload, list):
            archives = payload
            total = None
        elif isinstance(payload, dict) and isinstance(
            payload.get("archives"), list
        ):
            archives = payload["archives"]
            total = payload.get("total")
        else:
            raise BambuddyProtocolError(
                "Die Bambuddy-Archivantwort hat ein unbekanntes Format."
            )
        if total is not None and (not isinstance(total, int) or total < 0):
            raise BambuddyProtocolError(
                "Die Bambuddy-Archivanzahl hat ein unbekanntes Format."
            )
        return BambuddyConnectionInfo(
            total_archives=total,
            returned_archives=len(archives),
        )
