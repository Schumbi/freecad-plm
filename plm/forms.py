from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import Group

from .fcstd import validate_fcstd_upload
from .models import ApiToken, ExportJob, ManufacturingFile, ManufacturingMachine, Part, Project, Revision
from .permissions import ROLE_ADMIN, ROLE_EDITOR, ROLE_NAMES, ROLE_READER
from .services import inspect_manufacturing_upload


TOKEN_PRESET_READ = "read"
TOKEN_PRESET_ADDON = "addon"
TOKEN_PRESET_ADMIN = "admin"
TOKEN_PRESET_CHOICES = (
    (TOKEN_PRESET_READ, "Nur Lesen"),
    (TOKEN_PRESET_ADDON, "Addon Standard"),
    (TOKEN_PRESET_ADMIN, "Admin/Vollzugriff"),
)
TOKEN_PRESET_LABELS = dict(TOKEN_PRESET_CHOICES)
TOKEN_PRESET_SCOPES = {
    TOKEN_PRESET_READ: [ApiToken.Scope.READ],
    TOKEN_PRESET_ADDON: [
        ApiToken.Scope.READ,
        ApiToken.Scope.WRITE,
        ApiToken.Scope.CHECKOUT,
    ],
    TOKEN_PRESET_ADMIN: [
        ApiToken.Scope.READ,
        ApiToken.Scope.WRITE,
        ApiToken.Scope.CHECKOUT,
        ApiToken.Scope.ADMIN,
    ],
}


class UserManagementForm(forms.ModelForm):
    role = forms.ChoiceField(
        label="Rolle",
        choices=(
            (ROLE_READER, "Reader"),
            (ROLE_EDITOR, "Editor"),
            (ROLE_ADMIN, "Admin"),
        ),
    )
    password = forms.CharField(
        label="Initiales Passwort",
        required=False,
        widget=forms.PasswordInput,
        help_text="Beim Anlegen erforderlich. Bei Bearbeitung leer lassen.",
    )

    class Meta:
        model = get_user_model()
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "is_active",
        ]
        labels = {
            "username": "Benutzername",
            "first_name": "Vorname",
            "last_name": "Nachname",
            "email": "E-Mail",
            "is_active": "Aktiv",
        }

    def __init__(self, *args, **kwargs):
        self.is_create = kwargs.pop("is_create", False)
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            role = user_role(self.instance) or ROLE_READER
            self.fields["role"].initial = role
        self.fields["password"].required = self.is_create

    def clean_username(self):
        return self.cleaned_data["username"].strip()

    def clean_email(self):
        return self.cleaned_data["email"].strip()


class AdminSetPasswordForm(SetPasswordForm):
    pass


class ApiTokenForm(forms.ModelForm):
    preset = forms.ChoiceField(label="Rechte", choices=TOKEN_PRESET_CHOICES)
    expires_at = forms.DateTimeField(
        label="Ablaufdatum",
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"],
        help_text="Leer lassen fuer kein Ablaufdatum.",
    )

    class Meta:
        model = ApiToken
        fields = ["name", "preset", "expires_at"]
        labels = {
            "name": "Name",
        }

    def __init__(self, *args, token_user=None, **kwargs):
        self.token_user = token_user
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["preset"].initial = token_preset_for_scopes(self.instance.scopes)

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean_preset(self):
        preset = self.cleaned_data["preset"]
        if preset == TOKEN_PRESET_ADMIN and not user_has_admin_role(self.token_user):
            raise forms.ValidationError(
                "Admin/Vollzugriff ist nur fuer PLM-Admins erlaubt."
            )
        return preset

    @property
    def scopes(self):
        return list(TOKEN_PRESET_SCOPES[self.cleaned_data["preset"]])


def user_role(user):
    if user.groups.filter(name=ROLE_ADMIN).exists():
        return ROLE_ADMIN
    if user.groups.filter(name=ROLE_EDITOR).exists():
        return ROLE_EDITOR
    if user.groups.filter(name=ROLE_READER).exists():
        return ROLE_READER
    return ""


def user_has_admin_role(user):
    if user is None:
        return False
    return user.is_superuser or user.groups.filter(name=ROLE_ADMIN).exists()


def set_user_role(user, role):
    groups = {}
    for role_name in ROLE_NAMES:
        groups[role_name], _created = Group.objects.get_or_create(name=role_name)
    user.groups.remove(*groups.values())
    if role in groups:
        user.groups.add(groups[role])


def token_preset_for_scopes(scopes):
    scope_set = set(scopes or [])
    for preset, preset_scopes in TOKEN_PRESET_SCOPES.items():
        if scope_set == set(preset_scopes):
            return preset
    if ApiToken.Scope.ADMIN in scope_set:
        return TOKEN_PRESET_ADMIN
    if ApiToken.Scope.WRITE in scope_set or ApiToken.Scope.CHECKOUT in scope_set:
        return TOKEN_PRESET_ADDON
    return TOKEN_PRESET_READ


def token_preset_label(preset):
    return TOKEN_PRESET_LABELS.get(preset, preset)


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["code", "name", "status", "project_date", "description"]
        widgets = {
            "project_date": forms.DateInput(
                attrs={"type": "date"},
                format="%Y-%m-%d",
            ),
            "description": forms.Textarea(attrs={"rows": 4}),
        }
        labels = {
            "code": "Code",
            "name": "Name",
            "status": "Status",
            "project_date": "Datum",
            "description": "Beschreibung",
        }

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


class PartForm(forms.ModelForm):
    file = forms.FileField(label="Initiale FCStd-Datei")
    change_summary = forms.CharField(
        label="Aenderungen",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Kurz dokumentieren, was diese initiale Revision enthaelt.",
    )

    class Meta:
        model = Part
        fields = [
            "number",
            "name",
            "category",
            "description",
            "material",
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
    change_summary = forms.CharField(
        label="Aenderungen",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )

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


class RevisionExportJobForm(forms.Form):
    export_format = forms.ChoiceField(
        label="Format",
        choices=ExportJob.ExportFormat.choices,
    )
    selected_objects = forms.MultipleChoiceField(
        label="Objekte",
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, revision=None, **kwargs):
        super().__init__(*args, **kwargs)
        objects = (
            (revision.extracted_metadata or {})
            .get("freecadcmd", {})
            .get("objects", [])
            if revision
            else []
        )
        choices = []
        for item in objects:
            if not item.get("exportable"):
                continue
            name = item.get("name", "")
            label = item.get("label") or name
            type_id = item.get("type", "")
            choices.append((name, f"{label} ({name}, {type_id})"))
        self.fields["selected_objects"].choices = choices


class ManufacturingFileUploadForm(forms.ModelForm):
    file = forms.FileField(label="Fertigungsdatei")

    class Meta:
        model = ManufacturingFile
        fields = [
            "file",
            "purpose",
            "label",
            "description",
            "slicer_name",
            "slicer_version",
            "machine",
            "machine_label",
            "printer_profile",
            "material",
            "material_brand",
            "nozzle_diameter",
            "layer_height",
            "estimated_print_time_seconds",
            "estimated_material_g",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "purpose": "Zweck",
            "label": "Label",
            "description": "Beschreibung",
            "slicer_name": "Slicer",
            "slicer_version": "Slicer-Version",
            "machine": "Herstellungsmaschine",
            "machine_label": "Maschine/Freitext",
            "printer_profile": "Druckerprofil",
            "material": "Material",
            "material_brand": "Materialhersteller",
            "nozzle_diameter": "Duese mm",
            "layer_height": "Layerhoehe mm",
            "estimated_print_time_seconds": "Geschaetzte Druckzeit Sekunden",
            "estimated_material_g": "Geschaetztes Material g",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.upload_info = None
        self.fields["machine"].queryset = ManufacturingMachine.objects.filter(
            is_active=True
        )
        for field_name in [
            "machine",
            "label",
            "description",
            "slicer_name",
            "slicer_version",
            "machine_label",
            "printer_profile",
            "material",
            "material_brand",
        ]:
            self.fields[field_name].required = False

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        self.upload_info = inspect_manufacturing_upload(uploaded_file)
        return uploaded_file

    def clean(self):
        cleaned_data = super().clean()
        if self.upload_info:
            cleaned_data["file_type"] = self.upload_info["file_type"]
        return cleaned_data
