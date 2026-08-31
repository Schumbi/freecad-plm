import json
import tempfile
from io import BytesIO
from urllib.error import HTTPError
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
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
from .models import AuditEvent, ManufacturingFile, Part, Project, Revision
from .permissions import ROLE_ADMIN, ROLE_READER
from .services.bambuddy import plm_revision_url, sync_bambuddy_source_projects


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
            "http://bambuddy.example:8000/api/v1/archives/?limit=1&offset=0",
        )
        self.assertEqual(request.get_header("X-api-key"), "bb_secret")
        self.assertEqual(kwargs["timeout"], 7)

    def test_connection_accepts_bare_archive_list(self):
        client = BambuddyClient(
            "https://bambuddy.example",
            "bb_secret",
            opener=lambda *_args, **_kwargs: FakeResponse(
                json.dumps([{"id": 7}]).encode()
            ),
        )

        result = client.test_connection()

        self.assertEqual(result, BambuddyConnectionInfo(None, 1))

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

    def test_lists_bare_and_wrapped_archives(self):
        responses = iter(
            (
                FakeResponse(json.dumps([{"id": 1}]).encode()),
                FakeResponse(
                    json.dumps({"archives": [{"id": 2}], "total": 1}).encode()
                ),
            )
        )
        client = BambuddyClient(
            "https://bambuddy.example",
            "bb_secret",
            opener=lambda *_args, **_kwargs: next(responses),
        )

        self.assertEqual(client.list_archives(), [{"id": 1}])
        self.assertEqual(client.list_archives(), [{"id": 2}])

    def test_reads_archive_details(self):
        client = BambuddyClient(
            "https://bambuddy.example",
            "bb_secret",
            opener=lambda *_args, **_kwargs: FakeResponse(
                json.dumps({"id": 24, "status": "printing"}).encode()
            ),
        )

        self.assertEqual(
            client.get_archive(24),
            {"id": 24, "status": "printing"},
        )

    def test_reads_effective_permissions(self):
        client = BambuddyClient(
            "https://bambuddy.example",
            "bb_secret",
            opener=lambda *_args, **_kwargs: FakeResponse(
                json.dumps(
                    {"permissions": ["archives:read_all", "archives:update_all"]}
                ).encode()
            ),
        )

        self.assertEqual(
            client.get_effective_permissions(),
            {"archives:read_all", "archives:update_all"},
        )

    def test_uploads_source_3mf_as_multipart(self):
        requests = []

        def opener(request, **kwargs):
            requests.append((request, kwargs))
            return FakeResponse(
                json.dumps(
                    {
                        "status": "uploaded",
                        "archive_id": 24,
                        "source_3mf_path": "archive/24/source/A-001_R0007.3mf",
                    }
                ).encode()
            )

        client = BambuddyClient(
            "https://bambuddy.example",
            "bb_secret",
            timeout_seconds=9,
            opener=opener,
        )

        result = client.upload_source_3mf(
            24,
            BytesIO(b"PK\x03\x04source-3mf"),
            "A-001_R0007.3mf",
        )

        self.assertEqual(result["archive_id"], 24)
        request, kwargs = requests[0]
        self.assertEqual(
            request.full_url,
            "https://bambuddy.example/api/v1/archives/24/source",
        )
        self.assertEqual(request.method, "POST")
        self.assertIn("multipart/form-data; boundary=", request.get_header("Content-type"))
        self.assertIn(b'filename="A-001_R0007.3mf"', request.data)
        self.assertIn(b"PK\x03\x04source-3mf", request.data)
        self.assertEqual(kwargs["timeout"], 9)

    def test_updates_archive_external_url_with_patch(self):
        requests = []
        external_url = "https://plm.example/parts/3/#revision-9"

        def opener(request, **kwargs):
            requests.append((request, kwargs))
            return FakeResponse(
                json.dumps({"id": 24, "external_url": external_url}).encode()
            )

        client = BambuddyClient(
            "https://bambuddy.example",
            "bb_secret",
            timeout_seconds=9,
            opener=opener,
        )

        result = client.update_archive_external_url(24, external_url)

        self.assertEqual(result["external_url"], external_url)
        request, kwargs = requests[0]
        self.assertEqual(
            request.full_url,
            "https://bambuddy.example/api/v1/archives/24",
        )
        self.assertEqual(request.method, "PATCH")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(
            json.loads(request.data),
            {"external_url": external_url},
        )
        self.assertEqual(kwargs["timeout"], 9)

    def test_rejects_invalid_external_url_before_request(self):
        opener = Mock()
        client = BambuddyClient(
            "https://bambuddy.example",
            "bb_secret",
            opener=opener,
        )

        with self.assertRaises(BambuddyProtocolError):
            client.update_archive_external_url(24, "javascript:alert(1)")

        opener.assert_not_called()


@override_settings(PLM_PUBLIC_URL="https://plm.example")
class BambuddySourceSyncTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_root.cleanup)
        media_override = self.settings(MEDIA_ROOT=self.media_root.name)
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.user = get_user_model().objects.create_user(username="source-sync")

    def make_slicer_project(self, project_code="P7", part_number="A-001"):
        project = Project.objects.create(code=project_code, name=project_code)
        part = Part.objects.create(
            project=project,
            number=part_number,
            name=part_number,
        )
        revision = Revision.objects.create(
            part=part,
            revision_code="R0007",
            file=SimpleUploadedFile("Kleberschale.FCStd", b"fcstd"),
            original_filename="Kleberschale.FCStd",
            sha256="a" * 64,
            size_bytes=5,
            created_by=self.user,
        )
        return ManufacturingFile.objects.create(
            revision=revision,
            file_type=ManufacturingFile.FileType.SLICER_PROJECT_3MF,
            purpose=ManufacturingFile.Purpose.PRINT,
            status=ManufacturingFile.Status.DRAFT,
            file=SimpleUploadedFile("A-001_R0007.3mf", b"PK\x03\x04source"),
            original_filename="A-001_R0007.3mf",
            sha256="b" * 64,
            size_bytes=10,
            uploaded_by=self.user,
        )

    @override_settings(PLM_PUBLIC_URL="")
    def test_revision_link_requires_public_plm_url(self):
        slicer_project = self.make_slicer_project()

        with self.assertRaisesMessage(BambuddyProtocolError, "PLM_PUBLIC_URL"):
            plm_revision_url(slicer_project.revision)

    def test_uploads_exact_matching_source_to_running_archive(self):
        slicer_project = self.make_slicer_project()

        class FakeClient:
            def __init__(self):
                self.uploads = []
                self.links = []

            def list_archives(self, limit):
                self.limit = limit
                return [
                    {
                        "id": 24,
                        "printer_id": 1,
                        "print_name": "P7_A-001_R0007",
                        "status": "printing",
                        "source_3mf_path": None,
                        "external_url": None,
                    }
                ]

            def update_archive_external_url(self, archive_id, external_url):
                self.links.append((archive_id, external_url))
                return {"id": archive_id, "external_url": external_url}

            def upload_source_3mf(self, archive_id, source_file, filename):
                self.uploads.append((archive_id, source_file.read(), filename))
                return {
                    "status": "uploaded",
                    "source_3mf_path": "archive/24/source/P7_A-001_R0007.3mf",
                }

            def get_archive(self, archive_id):
                return {
                    "id": archive_id,
                    "status": "printing",
                    "source_3mf_path": None,
                    "external_url": None,
                }

        client = FakeClient()
        result = sync_bambuddy_source_projects(
            client=client,
            printer_ids=[1],
            limit=7,
        )

        self.assertEqual(result.inspected, 1)
        self.assertEqual(result.matched, 1)
        self.assertEqual(result.uploaded, 1)
        self.assertEqual(result.linked, 1)
        self.assertEqual(client.limit, 7)
        self.assertEqual(
            client.uploads,
            [(24, b"PK\x03\x04source", "A-001_R0007.3mf")],
        )
        expected_url = (
            f"https://plm.example/parts/{slicer_project.revision.part_id}/"
            f"#revision-{slicer_project.revision_id}"
        )
        self.assertEqual(client.links, [(24, expected_url)])
        slicer_project.refresh_from_db()
        history = slicer_project.metadata["bambuddy_source_archives"]
        self.assertEqual(history[0]["archive_id"], 24)
        self.assertEqual(history[0]["source_sha256"], "b" * 64)
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.BAMBUDDY_SOURCE_ATTACHED
        )
        self.assertEqual(event.metadata["bambuddy_archive_id"], 24)
        link_event = AuditEvent.objects.get(
            action=AuditEvent.Action.BAMBUDDY_REVISION_LINKED
        )
        self.assertEqual(link_event.metadata["revision_url"], expected_url)

    def test_dry_run_does_not_upload_or_change_metadata(self):
        slicer_project = self.make_slicer_project()
        client = Mock()
        client.list_archives.return_value = [
            {
                "id": 24,
                "printer_id": 1,
                "print_name": "P7_A-001_R0007",
                "status": "printing",
                "source_3mf_path": None,
                "external_url": None,
            }
        ]

        result = sync_bambuddy_source_projects(
            client=client,
            printer_ids=[1],
            dry_run=True,
        )

        self.assertEqual(result.matched, 1)
        self.assertEqual(result.uploaded, 0)
        self.assertEqual(result.linked, 0)
        client.upload_source_3mf.assert_not_called()
        client.update_archive_external_url.assert_not_called()
        slicer_project.refresh_from_db()
        self.assertNotIn("bambuddy_source_archives", slicer_project.metadata)

    def test_rechecks_archive_before_upload_and_preserves_existing_source(self):
        self.make_slicer_project()
        client = Mock()
        client.list_archives.return_value = [
            {
                "id": 24,
                "printer_id": 1,
                "print_name": "P7_A-001_R0007",
                "status": "printing",
                "source_3mf_path": None,
                "external_url": None,
            }
        ]
        client.get_archive.return_value = {
            "id": 24,
            "status": "printing",
            "source_3mf_path": "archive/24/source/manual.3mf",
            "external_url": "https://example.invalid/manual-link",
        }

        result = sync_bambuddy_source_projects(client=client, printer_ids=[1])

        self.assertEqual(result.matched, 1)
        self.assertEqual(result.already_attached, 1)
        self.assertEqual(result.uploaded, 0)
        client.upload_source_3mf.assert_not_called()

    def test_links_completed_archive_with_existing_source(self):
        slicer_project = self.make_slicer_project()
        client = Mock()
        client.list_archives.return_value = [
            {
                "id": 24,
                "printer_id": 1,
                "print_name": "P7_A-001_R0007",
                "status": "completed",
                "source_3mf_path": "archive/24/source/A-001_R0007.3mf",
                "external_url": None,
            }
        ]
        client.get_archive.return_value = client.list_archives.return_value[0]

        result = sync_bambuddy_source_projects(client=client, printer_ids=[1])

        expected_url = (
            f"https://plm.example/parts/{slicer_project.revision.part_id}/"
            f"#revision-{slicer_project.revision_id}"
        )
        self.assertEqual(result.linked, 1)
        self.assertEqual(result.uploaded, 0)
        client.update_archive_external_url.assert_called_once_with(24, expected_url)
        client.upload_source_3mf.assert_not_called()
        slicer_project.refresh_from_db()
        self.assertEqual(
            slicer_project.metadata["bambuddy_revision_links"][0]["revision_url"],
            expected_url,
        )

    def test_uploads_source_for_completed_archive(self):
        self.make_slicer_project()
        existing_url = "https://example.invalid/manually-curated"
        client = Mock()
        archive = {
            "id": 24,
            "printer_id": 1,
            "print_name": "P7_A-001_R0007",
            "status": "completed",
            "source_3mf_path": None,
            "external_url": existing_url,
        }
        client.list_archives.return_value = [archive]
        client.get_archive.return_value = archive
        client.upload_source_3mf.return_value = {
            "status": "uploaded",
            "source_3mf_path": "archive/24/source/A-001_R0007.3mf",
        }

        result = sync_bambuddy_source_projects(client=client, printer_ids=[1])

        self.assertEqual(result.already_linked, 1)
        self.assertEqual(result.linked, 0)
        self.assertEqual(result.uploaded, 1)
        client.update_archive_external_url.assert_not_called()

    def test_ambiguous_part_and_revision_name_is_not_uploaded(self):
        self.make_slicer_project(project_code="P7")
        self.make_slicer_project(project_code="P8")
        client = Mock()
        client.list_archives.return_value = [
            {
                "id": 24,
                "printer_id": 1,
                "print_name": "A-001_R0007",
                "status": "printing",
                "source_3mf_path": None,
                "external_url": None,
            }
        ]

        result = sync_bambuddy_source_projects(client=client, printer_ids=[1])

        self.assertEqual(result.ambiguous, 1)
        self.assertEqual(result.uploaded, 0)
        client.upload_source_3mf.assert_not_called()

    def test_project_prefix_selects_matching_duplicate_part_number(self):
        first = self.make_slicer_project(project_code="P7")
        self.make_slicer_project(project_code="P8")
        client = Mock()
        client.list_archives.return_value = [
            {
                "id": 24,
                "printer_id": 1,
                "print_name": "P7_A-001_R0007",
                "status": "printing",
                "source_3mf_path": None,
                "external_url": "https://example.invalid/linked",
            }
        ]
        client.get_archive.return_value = client.list_archives.return_value[0]
        client.upload_source_3mf.return_value = {
            "status": "uploaded",
            "source_3mf_path": "archive/24/source/P7_A-001_R0007.3mf",
        }

        result = sync_bambuddy_source_projects(client=client, printer_ids=[1])

        self.assertEqual(result.matched, 1)
        self.assertEqual(result.uploaded, 1)
        client.upload_source_3mf.assert_called_once()
        first.refresh_from_db()
        self.assertEqual(
            first.metadata["bambuddy_source_archives"][0]["archive_id"], 24
        )

    def test_skips_other_printers_and_already_synchronized_archives(self):
        self.make_slicer_project()
        client = Mock()
        client.list_archives.return_value = [
            {
                "id": 1,
                "printer_id": 2,
                "print_name": "P7_A-001_R0007",
                "status": "printing",
                "source_3mf_path": None,
                "external_url": None,
            },
            {
                "id": 2,
                "printer_id": 1,
                "print_name": "P7_A-001_R0007",
                "status": "completed",
                "source_3mf_path": None,
                "external_url": "https://plm.example/parts/1/#revision-1",
            },
            {
                "id": 3,
                "printer_id": 1,
                "print_name": "A-001_R0007",
                "status": "printing",
                "source_3mf_path": "archive/3/source/project.3mf",
                "external_url": "https://plm.example/parts/1/#revision-1",
            },
        ]

        result = sync_bambuddy_source_projects(client=client, printer_ids=[1])

        self.assertEqual(result.skipped_printer, 1)
        self.assertEqual(result.skipped_status, 0)
        self.assertEqual(result.already_attached, 1)
        self.assertEqual(result.already_linked, 2)
        client.upload_source_3mf.assert_not_called()
        client.update_archive_external_url.assert_not_called()


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
        PLM_PUBLIC_URL="https://plm.example",
    )
    def test_admin_sees_configuration_without_api_key_value(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("plm:integration_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "http://bambuddy.example:8000")
        self.assertContains(response, "https://plm.example")
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
        from_settings.return_value.get_effective_permissions.return_value = {
            "archives:read_all",
            "archives:update_all",
        }
        self.client.force_login(self.admin)

        response = self.client.post(reverse("plm:integration_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Verbindung erfolgreich")
        self.assertContains(response, "23 Archiv(e)")
        self.assertContains(response, "Source-3MF-Upload und Revisionslink sind berechtigt")

    @override_settings(
        BAMBUDDY_URL="http://bambuddy.example:8000",
        BAMBUDDY_API_KEY="bb_hidden_secret",
        BAMBUDDY_TIMEOUT_SECONDS=10,
    )
    @patch("plm.views.integrations.BambuddyClient.from_settings")
    def test_admin_sees_returned_count_for_bare_archive_list(self, from_settings):
        from_settings.return_value.test_connection.return_value = (
            BambuddyConnectionInfo(total_archives=None, returned_archives=1)
        )
        from_settings.return_value.get_effective_permissions.return_value = {
            "archives:read_all"
        }
        self.client.force_login(self.admin)

        response = self.client.post(reverse("plm:integration_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mindestens 1 Archiv(e)")
        self.assertContains(response, "Manage Archives")

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
