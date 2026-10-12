import struct
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.test import SimpleTestCase
from defusedxml.common import DTDForbidden, EntitiesForbidden

from .fcstd import fcstd_viewer_colors


class ViewerColorsTests(SimpleTestCase):
    def read_colors(self, xml=None, members=None):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "colors.FCStd"
            with ZipFile(path, "w") as archive:
                archive.writestr("Document.xml", "<Document />")
                if xml is not None:
                    archive.writestr("GuiDocument.xml", xml)
                for name, content in (members or {}).items():
                    archive.writestr(name, content)
            return fcstd_viewer_colors(path)

    def test_old_shape_colors_and_white_are_preserved(self):
        xml = '<Document><ViewProvider name="Red"><Properties><Property name="ShapeColor"><PropertyColor value="4278190080"/></Property></Properties></ViewProvider><ViewProvider name="White"><Properties><Property name="ShapeColor"><PropertyColor value="4294967040"/></Property></Properties></ViewProvider></Document>'
        self.assertEqual(self.read_colors(xml), {"Red": "#FF0000", "White": "#FFFFFF"})

    def test_modern_appearance_uses_diffuse_color_not_ambient(self):
        for version in ("0", "2", "3"):
            with self.subTest(version=version):
                xml = f'<Document><ViewProvider name="Blue"><Properties><Property name="ShapeAppearance"><MaterialList file="Appearance" version="{version}"/></Property><Property name="ShapeColor"><PropertyColor value="4278190080"/></Property></Properties></ViewProvider></Document>'
                data = struct.pack("<IIIIIff", 1, 0x555555ff, 0x0000ffff, 0x888888ff, 0xff, 0.9, 0.0)
                self.assertEqual(self.read_colors(xml, {"Appearance": data}), {"Blue": "#0000FF"})

    def test_missing_or_truncated_appearance_falls_back_to_shape_color(self):
        xml = '<Document><ViewProvider name="Part"><Properties><Property name="ShapeAppearance"><MaterialList file="Appearance" version="3"/></Property><Property name="ShapeColor"><PropertyColor value="4278190080"/></Property></Properties></ViewProvider></Document>'
        self.assertEqual(self.read_colors(xml), {"Part": "#FF0000"})
        self.assertEqual(self.read_colors(xml, {"Appearance": b"short"}), {"Part": "#FF0000"})
        self.assertEqual(self.read_colors(), {})

    def test_gui_xml_entities_are_rejected(self):
        with self.assertRaises((DTDForbidden, EntitiesForbidden)):
            self.read_colors('<!DOCTYPE x [<!ENTITY x "red">]><Document>&x;</Document>')
