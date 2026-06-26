from django import forms

from .fcstd import validate_fcstd_upload
from .models import Revision


class RevisionUploadForm(forms.Form):
    file = forms.FileField(label="FCStd-Datei")

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        validate_fcstd_upload(uploaded_file)
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
