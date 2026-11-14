from pathlib import Path

from django.test import SimpleTestCase


class DialogVisibilityStylesTests(SimpleTestCase):
    def test_closed_dialogs_are_hidden_globally(self):
        stylesheet = Path(__file__).parent / "static/plm/app.css"
        css = stylesheet.read_text(encoding="utf-8")
        self.assertIn("dialog.plm-dialog:not([open]) {\n  display: none;\n}", css)
