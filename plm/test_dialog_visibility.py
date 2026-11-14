from pathlib import Path

from django.test import SimpleTestCase


class DialogVisibilityStylesTests(SimpleTestCase):
    def test_closed_dialogs_are_hidden_globally(self):
        stylesheet = Path(__file__).parent / "static/plm/app.css"
        css = stylesheet.read_text(encoding="utf-8")
        self.assertIn("dialog.plm-dialog:not([open]) {\n  display: none;\n}", css)


class ModelViewerInitializationTests(SimpleTestCase):
    def setUp(self):
        script = Path(__file__).parent / "static/plm/model-viewer.js"
        source = script.read_text(encoding="utf-8")
        self.open_viewer = source.split("async function openViewer", 1)[1].split(
            "\nfunction markerRadius", 1
        )[0]

    def test_dialog_opens_before_webgl_scene_is_created(self):
        self.assertLess(
            self.open_viewer.index("dialog.showModal()"),
            self.open_viewer.index("ensureScene()"),
        )

    def test_webgl_failure_is_reported_inside_the_dialog(self):
        self.assertIn("catch (error)", self.open_viewer)
        self.assertIn("webglUnavailableMessage()", self.open_viewer)
