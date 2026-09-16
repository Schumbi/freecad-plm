"""Real HTTP contract tests. Run with scripts/run_contract_tests.py.

Kept outside test*.py discovery: the standalone server suite must also run
without an addon checkout. The explicit runner fails if that checkout is absent.
"""
import os
from pathlib import Path
import sys
from unittest.mock import Mock

from django.test import LiveServerTestCase
from django.utils import timezone

from plm.models import ApiToken, Project
from plm.review_test_support import PrintProjectFixture, mesh_upload


ADDON = Path(os.environ.get("PLM_ADDON_SOURCE", Path(__file__).resolve().parents[2] / "freecad-plm-addon"))
if not (ADDON / "freecad_plm_addon" / "api_client.py").is_file():
    raise RuntimeError("Addon checkout missing; set PLM_ADDON_SOURCE to freecad-plm-addon.")
sys.path.insert(0, str(ADDON))

from freecad_plm_addon.api_client import PLMClient
from freecad_plm_addon.errors import AuthenticationError, ConflictError, NotFoundError, PermissionDeniedError
from freecad_plm_addon.panel import PLMPanel
from freecad_plm_addon.slicer import read_sync_state, validate_3mf, write_sync_state
from freecad_plm_addon.workspace import sha256_file


class AddonServerContracts(PrintProjectFixture, LiveServerTestCase):
    def setUp(self):
        super().setUp()
        self.api = PLMClient(self.live_server_url, self.raw_token, timeout=5)
        self.local = Path(self.media_root) / "local"
        self.local.mkdir()
        self.mesh = self.local / "Druckplatte ä.3mf"
        self.mesh.write_bytes(mesh_upload().read())

    def test_create_list_detail_upload_and_verified_download(self):
        created = self.api.create_print_project(self.revision.pk, "DP-2", "Platte ä", "Contract")
        again = self.api.create_print_project(self.revision.pk, "DP-2", "Platte ä", "Contract")
        self.assertEqual(created["id"], again["id"])
        self.assertEqual(created["primary_revision_id"], self.revision.pk)
        self.assertIsNone(created["slicer_project"])
        self.assertEqual({p["id"] for p in self.api.get_print_projects()}, {self.item.pk, created["id"]})
        result = self.api.sync_print_project(created["id"], self.mesh)
        self.assertEqual(result["id"], created["id"])
        file = result["slicer_project"]
        self.assertEqual(file["original_filename"], self.mesh.name)
        self.assertEqual(file["sha256"], sha256_file(self.mesh))
        self.assertEqual(file["size_bytes"], self.mesh.stat().st_size)
        self.assertEqual(result["plates"][0]["name"], "first")
        self.assertEqual(self.api.get_print_project(created["id"])["slicer_project"], file)
        target = self.local / "download.3mf"
        self.api.download_revision_file(file["download_url"], target, file["sha256"])
        self.assertEqual(target.read_bytes(), self.mesh.read_bytes())
        validate_3mf(target)

    def test_real_panel_sync_accepts_server_payload_and_records_hash(self):
        write_sync_state(self.mesh, {"print_project_id": self.item.pk, "server_sha256": ""})
        panel = Mock()
        panel.client.return_value = self.api
        self.assertTrue(PLMPanel._sync_slicer_project_path(panel, self.mesh, {"id": self.revision.pk}))
        state = read_sync_state(self.mesh)
        self.assertEqual(state["print_project_id"], self.item.pk)
        self.assertEqual(state["server_sha256"], sha256_file(self.mesh))
        self.assertEqual(state["sync_status"], "synchronized")


    def test_stale_print_project_upload_maps_to_conflict(self):
        first = self.api.sync_print_project(self.item.pk, self.mesh)
        base = first["slicer_project"]["sha256"]
        newer = self.local / "newer.3mf"
        newer.write_bytes(mesh_upload(marker="newer").read())
        current = self.api.sync_print_project(self.item.pk, newer, base_sha256=base)
        with self.assertRaises(ConflictError) as raised:
            self.api.sync_print_project(self.item.pk, self.mesh, base_sha256=base)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(
            self.api.get_print_project(self.item.pk)["slicer_project"]["sha256"],
            current["slicer_project"]["sha256"],
        )

    def test_sources_use_real_json_and_multipart_contracts(self):
        other = self.make_revision(self.project, "A-002")
        first = self.api.add_print_project_revision_source(self.item.pk, other.pk, "Deckel ä")
        second = self.api.add_print_project_revision_source(self.item.pk, other.pk, "Deckel ä")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["source_id"], second["source_id"])
        source = self.local / "Figur ä.stl"
        source.write_bytes(b"solid figure\nendsolid figure\n")
        external = self.api.add_print_project_source(self.item.pk, source, "Figur ä")
        sources = {s["id"]: s for s in self.api.get_print_project(self.item.pk)["sources"]}
        self.assertEqual(sources[first["source_id"]]["revision_id"], other.pk)
        self.assertEqual(sources[external["source_id"]]["sha256"], sha256_file(source))
        self.assertEqual(sources[external["source_id"]]["label"], "Figur ä")

    def test_foreign_project_source_is_a_conflict_without_mutation(self):
        foreign = Project.objects.create(code="OTHER", name="Other")
        revision = self.make_revision(foreign, "A-001")
        with self.assertRaises(ConflictError) as raised:
            self.api.add_print_project_revision_source(self.item.pk, revision.pk)
        self.assertEqual(raised.exception.status, 409)
        self.assertFalse(self.item.sources.exists())

    def test_revoked_token_maps_to_authentication_error(self):
        self.token.revoked_at = timezone.now()
        self.token.save(update_fields=["revoked_at"])
        with self.assertRaises(AuthenticationError) as raised:
            self.api.get_print_projects()
        self.assertEqual(raised.exception.status, 401)

    def test_read_only_token_maps_to_permission_error(self):
        self.token.scopes = [ApiToken.Scope.READ]
        self.token.save()
        with self.assertRaises(PermissionDeniedError) as raised:
            self.api.sync_print_project(self.item.pk, self.mesh)
        self.assertEqual(raised.exception.status, 403)
        self.item.refresh_from_db()
        self.assertFalse(self.item.slicer_file)

    def test_missing_file_maps_to_not_found(self):
        with self.assertRaises(NotFoundError) as raised:
            self.api.download_revision_file(
                f"{self.live_server_url}{self.url}file/", self.local / "missing.3mf", "a" * 64
            )
        self.assertEqual(raised.exception.status, 404)
        self.assertFalse((self.local / "missing.3mf").exists())

    def test_legacy_revision_slicer_contract_remains_compatible(self):
        result = self.api.sync_slicer_project(self.revision.pk, self.mesh, base_sha256="")
        self.assertTrue(result["created"])
        self.assertEqual(result["slicer_project"]["sha256"], sha256_file(self.mesh))
        current = self.api.get_slicer_project(self.revision.pk)
        self.assertEqual(current["id"], result["slicer_project"]["id"])
