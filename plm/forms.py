from django import forms

from .fcstd import validate_fcstd_upload


class RevisionUploadForm(forms.Form):
    file = forms.FileField(label="FCStd-Datei")

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        validate_fcstd_upload(uploaded_file)
        return uploaded_file
