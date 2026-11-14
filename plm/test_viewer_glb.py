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
