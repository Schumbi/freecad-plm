from django import forms

from .fcstd import validate_fcstd_upload
from .models import Part, Revision


class PartForm(forms.ModelForm):
    file = forms.FileField(label="Initiale FCStd-Datei")

    class Meta:
        model = Part
        fields = [
            "number",
            "name",
            "category",
            "description",
            "material",
            "supplier",
            "tags",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "number": "Teilenummer",
            "name": "Name",
            "category": "Typ",
            "description": "Beschreibung",
            "material": "Material",
            "supplier": "Lieferant",
            "tags": "Tags",
        }

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        self.fcstd_metadata = None
        self.fields["number"].required = False
        self.fields["name"].required = False
        self.fields["number"].help_text = (
            "Leer lassen, um die FreeCAD-Id oder automatisch P-001 zu nutzen."
        )
        self.fields["name"].help_text = "Leer lassen, um den FreeCAD-Label zu nutzen."

    def clean_number(self):
        number = self.cleaned_data["number"].strip()
        if self.project and self.project.parts.filter(number=number).exists():
            raise forms.ValidationError(
                "Diese Teilenummer existiert in diesem Projekt bereits."
            )
        return number

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        self.fcstd_metadata = validate_fcstd_upload(uploaded_file)
        return uploaded_file

    def clean(self):
        cleaned_data = super().clean()
        metadata = self.fcstd_metadata or {}
        properties = metadata.get("freecad_document", {}).get("properties", {})

        number = (cleaned_data.get("number") or "").strip()
        if not number and properties.get("Id"):
            number = properties["Id"].strip()
            if self.project and self.project.parts.filter(number=number).exists():
                self.add_error(
                    "number",
                    "Die FreeCAD-Id existiert in diesem Projekt bereits.",
                )
            cleaned_data["number"] = number

        name = (cleaned_data.get("name") or "").strip()
        if not name:
            name = properties.get("Label") or metadata.get("original_filename", "Teil")
            cleaned_data["name"] = name

        return cleaned_data


class RevisionUploadForm(forms.Form):
    file = forms.FileField(label="FCStd-Datei")

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        validate_fcstd_upload(uploaded_file)
        return uploaded_file


class ProjectSnapshotUploadForm(forms.Form):
    name = forms.CharField(label="Name", max_length=200, required=False)
    file = forms.FileField(label="Projekt-ZIP")

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        if not uploaded_file.name.lower().endswith(".zip"):
            raise forms.ValidationError("Bitte eine ZIP-Datei hochladen.")
        return uploaded_file


class RevisionNotesForm(forms.ModelForm):
    class Meta:
        model = Revision
        fields = ["notes"]
        widgets = {
            "notes": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": "Anmerkungen, naechste Schritte, Einbauhinweise ...",
                }
            )
        }
        labels = {"notes": "Anmerkungen"}
