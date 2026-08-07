import json
from urllib.error import HTTPError
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .integrations.bambuddy import (
    BambuddyAuthenticationError,
    BambuddyClient,
    BambuddyConfigurationError,
    BambuddyConnectionError,
    BambuddyConnectionInfo,
    BambuddyProtocolError,
)
from .permissions import ROLE_ADMIN, ROLE_READER


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        return self.payload


class BambuddyClientTests(SimpleTestCase):
    def test_connection_uses_read_only_archive_endpoint_and_api_key(self):
        requests = []

        def opener(request, **kwargs):
            requests.append((request, kwargs))
            return FakeResponse(
                json.dumps({"total": 12, "archives": [{"id": 7}]}).encode()
            )

        client = BambuddyClient(
            "http://bambuddy.example:8000/",
            "bb_secret",
            timeout_seconds=7,
            opener=opener,
        )

        result = client.test_connection()

        self.assertEqual(result, BambuddyConnectionInfo(12, 1))
        request, kwargs = requests[0]
        self.assertEqual(
            request.full_url,
            "http://bambuddy.example:8000/api/v1/archives?limit=1&offset=0",
        )
        self.assertEqual(request.get_header("X-api-key"), "bb_secret")
        self.assertEqual(kwargs["timeout"], 7)

    def test_api_v1_base_url_is_not_duplicated(self):
        client = BambuddyClient(
            "https://bambuddy.example/api/v1",
            "bb_secret",
            opener=Mock(),
        )

        self.assertEqual(
            client.api_url("archives/4"),
            "https://bambuddy.example/api/v1/archives/4",
        )

    def test_configuration_rejects_missing_or_unsafe_values(self):
        with self.assertRaises(BambuddyConfigurationError):
            BambuddyClient("", "bb_secret")
        with self.assertRaises(BambuddyConfigurationError):
            BambuddyClient("ftp://bambuddy.example", "bb_secret")
        with self.assertRaises(BambuddyConfigurationError):
            BambuddyClient("http://user:secret@bambuddy.example", "bb_secret")
        with self.assertRaises(BambuddyConfigurationError):
            BambuddyClient("http://bambuddy.example", "")
        with self.assertRaises(BambuddyConfigurationError):
            BambuddyClient("http://bambuddy.example", "bb_secret", 0)

    def test_authentication_error_does_not_expose_response_body_or_key(self):
        def opener(request, **_kwargs):
            raise HTTPError(
                request.full_url,
                403,
                "Forbidden bb_secret",
                hdrs=None,
                fp=None,
            )

        client = BambuddyClient(
            "http://bambuddy.example",
            "bb_secret",
            opener=opener,
        )

        with self.assertRaises(BambuddyAuthenticationError) as raised:
            client.test_connection()

        self.assertNotIn("bb_secret", str(raised.exception))

    def test_rejects_invalid_archive_payload(self):
        client = BambuddyClient(
            "http://bambuddy.example",
            "bb_secret",
            opener=lambda *_args, **_kwargs: FakeResponse(b'{"items": []}'),
        )

        with self.assertRaises(BambuddyProtocolError):
            client.test_connection()


class BambuddyIntegrationViewTests(TestCase):
    def setUp(self):
        admin_group, _created = Group.objects.get_or_create(name=ROLE_ADMIN)
        reader_group, _created = Group.objects.get_or_create(name=ROLE_READER)
        self.admin = get_user_model().objects.create_user(
            username="integration-admin",
            password="test-password",
        )
        self.admin.groups.add(admin_group)
        self.reader = get_user_model().objects.create_user(
            username="integration-reader",
            password="test-password",
        )
        self.reader.groups.add(reader_group)

    @override_settings(
        BAMBUDDY_URL="http://bambuddy.example:8000",
        BAMBUDDY_API_KEY="bb_hidden_secret",
        BAMBUDDY_TIMEOUT_SECONDS=10,
    )
    def test_admin_sees_configuration_without_api_key_value(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("plm:integration_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "http://bambuddy.example:8000")
        self.assertContains(response, "Gesetzt (Wert verborgen)")
        self.assertNotContains(response, "bb_hidden_secret")

    def test_reader_cannot_access_integrations(self):
        self.client.force_login(self.reader)

        response = self.client.get(reverse("plm:integration_settings"))

        self.assertEqual(response.status_code, 403)

    @override_settings(
        BAMBUDDY_URL="http://bambuddy.example:8000",
        BAMBUDDY_API_KEY="bb_hidden_secret",
        BAMBUDDY_TIMEOUT_SECONDS=10,
    )
    @patch("plm.views.integrations.BambuddyClient.from_settings")
    def test_admin_can_test_connection(self, from_settings):
        from_settings.return_value.test_connection.return_value = (
            BambuddyConnectionInfo(total_archives=23, returned_archives=1)
        )
        self.client.force_login(self.admin)

        response = self.client.post(reverse("plm:integration_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Verbindung erfolgreich")
        self.assertContains(response, "23 Archiv(e)")

    @override_settings(
        BAMBUDDY_URL="http://bambuddy.example:8000",
        BAMBUDDY_API_KEY="bb_hidden_secret",
        BAMBUDDY_TIMEOUT_SECONDS=10,
    )
    @patch("plm.views.integrations.BambuddyClient.from_settings")
    def test_connection_failure_is_shown_without_secret(self, from_settings):
        from_settings.return_value.test_connection.side_effect = (
            BambuddyConnectionError("Bambuddy ist nicht erreichbar.")
        )
        self.client.force_login(self.admin)

        response = self.client.post(reverse("plm:integration_settings"))

        self.assertEqual(response.status_code, 502)
        self.assertContains(
            response,
            "Bambuddy ist nicht erreichbar.",
            status_code=502,
        )
        self.assertNotContains(response, "bb_hidden_secret", status_code=502)
