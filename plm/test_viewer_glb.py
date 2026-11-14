import json
import struct
import sys
import types
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from .freecadcmd import FREECADCMD_SCRIPT


class _Point:
    __slots__ = ("x", "y", "z")

    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _MeshData:
    def __init__(self, points, facets):
        self.Topology = (points, facets)


class _Mesh:
    def __init__(self, label, points, facets):
        self.Label = label
        self.Mesh = _MeshData(points, facets)


def _load_script_functions():
    module = types.ModuleType("FreeCAD")
    previous = sys.modules.get("FreeCAD")
    sys.modules["FreeCAD"] = module
    namespace = {"__name__": "plm_freecadcmd_script"}
    try:
        exec(compile(FREECADCMD_SCRIPT, "plm_freecadcmd_script", "exec"), namespace)
    finally:
        if previous is None:
            sys.modules.pop("FreeCAD", None)
        else:
            sys.modules["FreeCAD"] = previous
    return namespace


class ViewerGlbTests(SimpleTestCase):
    def test_glb_contains_positions_indices_and_material(self):
        namespace = _load_script_functions()
        mesh = _Mesh(
            "Würfel",
            [_Point(0, 0, 0), _Point(10, 0, 0), _Point(0, 10, 0)],
            [(0, 1, 2)],
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "preview.glb"
            namespace["write_viewer_glb"]([mesh], ["#336699"], path)
            data = path.read_bytes()

        magic, version, total = struct.unpack_from("<4sII", data, 0)
        self.assertEqual(magic, b"glTF")
        self.assertEqual(version, 2)
        self.assertEqual(total, len(data))

        json_length, json_type = struct.unpack_from("<I4s", data, 12)
        self.assertEqual(json_type, b"JSON")
        document = json.loads(data[20:20 + json_length].decode("utf-8"))
        self.assertEqual(document["asset"]["version"], "2.0")
        self.assertEqual(len(document["meshes"]), 1)
        self.assertEqual(len(document["materials"]), 1)
        color = document["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"]
        self.assertAlmostEqual(color[0], 0x33 / 255, places=4)
        self.assertEqual(document["accessors"][0]["count"], 3)
        self.assertEqual(document["accessors"][1]["count"], 3)

        bin_length, bin_type = struct.unpack_from("<I4s", data, 20 + json_length)
        self.assertEqual(bin_type, b"BIN\x00")
        self.assertGreater(bin_length, 0)


from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from .freecadcmd import PREVIEW_GENERATOR_VERSION
from .models import ExportJob, Part, Project, Revision
from .views.common import ensure_revision_viewer_preview, revision_viewer_glb_artifact


class PreviewUnavailableTests(TestCase):
    def test_revision_without_solids_is_not_retried(self):
        user = get_user_model().objects.create_user("preview-user", password="pw")
        project = Project.objects.create(code="NOVIS", name="Ohne Solids")
        part = Part.objects.create(project=project, number="P-1", name="Parameter")
        revision = Revision.objects.create(
            part=part,
            revision_code="R0001",
            status=Revision.Status.DRAFT,
            file=SimpleUploadedFile("parameter.FCStd", b"x"),
            file_format=Revision.FileFormat.FCSTD,
            original_filename="parameter.FCStd",
            sha256="a" * 64,
            size_bytes=1,
            created_by=user,
        )
        ExportJob.objects.create(
            revision=revision,
            job_type=ExportJob.JobType.VIEWER,
            status=ExportJob.Status.FAILED,
            error="FreeCADCmd endete mit Code 1.",
            log="RuntimeError: Keine sichtbaren Volumenkoerper fuer Vorschau-Ansichten gefunden.",
            created_by=user,
        )

        self.assertIsNone(revision_viewer_glb_artifact(revision))
        self.assertEqual(
            ensure_revision_viewer_preview(revision, user, process_inline=False),
            "failed",
        )
        self.assertFalse(
            ExportJob.objects.filter(
                revision=revision,
                status=ExportJob.Status.QUEUED,
            ).exists()
        )
