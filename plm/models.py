from uuid import uuid4

from django.db import models
from django.conf import settings
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Project(TimeStampedModel):
    class Status(models.TextChoices):
        RUNNING = "running", "Laufend"
        COMPLETED = "completed", "Abgeschlossen"
        IDEA = "idea", "Idee"
        IMPORTANT = "important", "Wichtig"
        ORDER = "order", "Auftrag"

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RUNNING,
    )
    project_date = models.DateField(default=timezone.localdate)
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class Part(TimeStampedModel):
    class Category(models.TextChoices):
        PART = "part", "Teil"
        ASSEMBLY = "assembly", "Baugruppe"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="parts")
    number = models.CharField(max_length=80)
    name = models.CharField(max_length=200)
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.PART,
    )
    description = models.TextField(blank=True)
    material = models.CharField(max_length=120, blank=True)
    supplier = models.CharField(max_length=160, blank=True)
    tags = models.CharField(max_length=255, blank=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["project__code", "number"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "number"],
                name="unique_part_number_per_project",
            ),
        ]

    def __str__(self):
        return f"{self.number} - {self.name}"


def revision_upload_path(instance, filename):
    project_id = instance.part.project_id or "unassigned-project"
    part_id = instance.part_id or "unassigned-part"
    return f"projects/{project_id}/parts/{part_id}/revisions/{instance.revision_code}/{filename}"


def revision_artifact_upload_path(instance, filename):
    revision = instance.revision
    project_id = revision.part.project_id or "unassigned-project"
    part_id = revision.part_id or "unassigned-part"
    artifact_type = instance.artifact_type or "artifact"
    return (
        f"projects/{project_id}/parts/{part_id}/revisions/"
        f"{revision.revision_code}/artifacts/{artifact_type}/{filename}"
    )


def manufacturing_file_upload_path(instance, filename):
    revision = instance.revision
    project_id = revision.part.project_id or "unassigned-project"
    part_id = revision.part_id or "unassigned-part"
    return (
        f"projects/{project_id}/parts/{part_id}/revisions/"
        f"{revision.revision_code}/manufacturing/{instance.storage_key}/{filename}"
    )


def manufacturing_thumbnail_upload_path(instance, filename):
    revision = instance.revision
    project_id = revision.part.project_id or "unassigned-project"
    part_id = revision.part_id or "unassigned-part"
    return (
        f"projects/{project_id}/parts/{part_id}/revisions/"
        f"{revision.revision_code}/manufacturing/{instance.storage_key}/preview/{filename}"
    )


def manufacturing_run_attachment_upload_path(instance, filename):
    manufacturing_file = instance.run.manufacturing_file
    revision = manufacturing_file.revision
    project_id = revision.part.project_id or "unassigned-project"
    part_id = revision.part_id or "unassigned-part"
    return (
        f"projects/{project_id}/parts/{part_id}/revisions/"
        f"{revision.revision_code}/manufacturing/{manufacturing_file.storage_key}/"
        f"runs/{instance.run_id}/attachments/{filename}"
    )


class Revision(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Entwurf"
        RELEASED = "released", "Freigegeben"
        OBSOLETE = "obsolete", "Obsolet"

    part = models.ForeignKey(Part, on_delete=models.PROTECT, related_name="revisions")
    revision_code = models.CharField(max_length=20)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    file = models.FileField(upload_to=revision_upload_path)
    original_filename = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    notes = models.TextField(blank=True)
    extracted_metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_revisions",
    )
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["part__project__code", "part__number", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["part", "revision_code"],
                name="unique_revision_code_per_part",
            ),
        ]

    def __str__(self):
        return f"{self.part.number} {self.revision_code}"


class ExportJob(TimeStampedModel):
    class JobType(models.TextChoices):
        INSPECT = "inspect", "FreeCAD-Analyse"
        EXPORT = "export", "Export"
        PNG_VIEWS = "png_views", "PNG-Ansichten"

    class Status(models.TextChoices):
        QUEUED = "queued", "Wartend"
        RUNNING = "running", "Laeuft"
        SUCCEEDED = "succeeded", "Erfolgreich"
        FAILED = "failed", "Fehlgeschlagen"

    class ExportFormat(models.TextChoices):
        STEP = "step", "STEP"
        STL = "stl", "STL"
        THREEMF = "3mf", "3MF"

    revision = models.ForeignKey(
        Revision,
        on_delete=models.PROTECT,
        related_name="export_jobs",
    )
    job_type = models.CharField(max_length=20, choices=JobType.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
    )
    export_format = models.CharField(
        max_length=10,
        choices=ExportFormat.choices,
        blank=True,
    )
    selected_objects = models.JSONField(default=list, blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    log = models.TextField(blank=True)
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_export_jobs",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.revision} {self.job_type} {self.status}"


class RevisionArtifact(TimeStampedModel):
    class ArtifactType(models.TextChoices):
        STEP = "step", "STEP"
        STL = "stl", "STL"
        THREEMF = "3mf", "3MF"
        PNG = "png", "PNG"

    revision = models.ForeignKey(
        Revision,
        on_delete=models.PROTECT,
        related_name="artifacts",
    )
    job = models.ForeignKey(
        ExportJob,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="artifacts",
    )
    artifact_type = models.CharField(max_length=10, choices=ArtifactType.choices)
    view_name = models.CharField(max_length=40, blank=True)
    file = models.FileField(upload_to=revision_artifact_upload_path)
    original_filename = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["revision__part__project__code", "revision__part__number", "artifact_type", "view_name", "created_at"]

    def __str__(self):
        label = self.view_name or self.artifact_type
        return f"{self.revision} {label}"


class ManufacturingMachine(TimeStampedModel):
    class MachineType(models.TextChoices):
        PRINTER_3D = "printer_3d", "3D-Drucker"
        CNC = "cnc", "CNC"
        LASER = "laser", "Laser"
        EXTERNAL = "external", "Externer Fertiger"
        OTHER = "other", "Sonstige"

    name = models.CharField(max_length=160)
    machine_type = models.CharField(
        max_length=20,
        choices=MachineType.choices,
        default=MachineType.PRINTER_3D,
    )
    manufacturer = models.CharField(max_length=120, blank=True)
    model = models.CharField(max_length=120, blank=True)
    serial_number = models.CharField(max_length=120, blank=True)
    network_address = models.CharField(max_length=255, blank=True)
    integration_kind = models.CharField(
        max_length=80,
        blank=True,
        help_text="Spaeter z.B. bambulab, octoprint, moonraker oder vendor-api.",
    )
    metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ManufacturingFile(TimeStampedModel):
    class FileType(models.TextChoices):
        SLICER_3MF = "slicer_3mf", "Slicer-3MF"
        GCODE = "gcode", "G-Code"
        BGCODE = "bgcode", "Bambu/Prusa BGCode"
        STL_PRINT = "stl_print", "STL Fertigung"
        STEP_VENDOR = "step_vendor", "STEP Fertiger"
        PDF_DRAWING = "pdf_drawing", "Fertigungs-PDF"
        OTHER = "other", "Sonstige"

    class Purpose(models.TextChoices):
        PRINT = "print", "3D-Druck"
        EXTERNAL_MANUFACTURING = "external_manufacturing", "Externe Fertigung"
        INSPECTION = "inspection", "Pruefung"
        DOCUMENTATION = "documentation", "Dokumentation"

    class Status(models.TextChoices):
        DRAFT = "draft", "Entwurf"
        APPROVED = "approved", "Freigegeben"
        PRINTED = "printed", "Gedruckt"
        OBSOLETE = "obsolete", "Obsolet"

    revision = models.ForeignKey(
        Revision,
        on_delete=models.PROTECT,
        related_name="manufacturing_files",
    )
    storage_key = models.UUIDField(default=uuid4, editable=False, unique=True)
    file_type = models.CharField(
        max_length=30,
        choices=FileType.choices,
        default=FileType.SLICER_3MF,
    )
    purpose = models.CharField(
        max_length=30,
        choices=Purpose.choices,
        default=Purpose.PRINT,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.APPROVED,
    )
    file = models.FileField(upload_to=manufacturing_file_upload_path, max_length=500)
    thumbnail = models.FileField(
        upload_to=manufacturing_thumbnail_upload_path,
        max_length=500,
        blank=True,
    )
    thumbnail_original_filename = models.CharField(max_length=255, blank=True)
    original_filename = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    label = models.CharField(max_length=160, blank=True)
    description = models.TextField(blank=True)
    slicer_name = models.CharField(max_length=120, blank=True)
    slicer_version = models.CharField(max_length=80, blank=True)
    machine = models.ForeignKey(
        ManufacturingMachine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="manufacturing_files",
    )
    machine_label = models.CharField(max_length=160, blank=True)
    printer_profile = models.CharField(max_length=160, blank=True)
    material = models.CharField(max_length=120, blank=True)
    material_brand = models.CharField(max_length=120, blank=True)
    nozzle_diameter = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    layer_height = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    estimated_print_time_seconds = models.PositiveIntegerField(null=True, blank=True)
    estimated_material_g = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_manufacturing_files",
    )

    class Meta:
        ordering = ["revision__part__project__code", "revision__part__number", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["revision", "sha256"],
                name="unique_manufacturing_file_sha_per_revision",
            ),
        ]

    def __str__(self):
        label = self.label or self.original_filename
        return f"{self.revision} {label}"


class ManufacturingRun(TimeStampedModel):
    class Status(models.TextChoices):
        PLANNED = "planned", "Geplant"
        RUNNING = "running", "Laeuft"
        SUCCEEDED = "succeeded", "Erfolgreich"
        FAILED = "failed", "Fehlgeschlagen"
        SCRAPPED = "scrapped", "Ausschuss"

    manufacturing_file = models.ForeignKey(
        ManufacturingFile,
        on_delete=models.PROTECT,
        related_name="runs",
    )
    machine = models.ForeignKey(
        ManufacturingMachine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="runs",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PLANNED,
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="manufacturing_runs",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    material_batch = models.CharField(max_length=160, blank=True)
    result_notes = models.TextField(blank=True)
    machine_report = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.manufacturing_file} {self.get_status_display()}"


class ManufacturingRunAttachment(TimeStampedModel):
    class AttachmentType(models.TextChoices):
        PHOTO = "photo", "Foto"
        LOG = "log", "Log"
        REPORT = "report", "Report"
        MEASUREMENT = "measurement", "Messprotokoll"
        OTHER = "other", "Sonstige"

    run = models.ForeignKey(
        ManufacturingRun,
        on_delete=models.PROTECT,
        related_name="attachments",
    )
    attachment_type = models.CharField(
        max_length=20,
        choices=AttachmentType.choices,
        default=AttachmentType.PHOTO,
    )
    file = models.FileField(
        upload_to=manufacturing_run_attachment_upload_path,
        max_length=500,
    )
    original_filename = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    caption = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_manufacturing_run_attachments",
    )

    class Meta:
        ordering = ["run", "attachment_type", "created_at"]

    def __str__(self):
        return f"{self.run} {self.original_filename}"


class Checkout(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Aktiv"
        COMPLETED = "completed", "Eingecheckt"
        CANCELED = "canceled", "Abgebrochen"

    part = models.ForeignKey(Part, on_delete=models.PROTECT, related_name="checkouts")
    base_revision = models.ForeignKey(
        Revision,
        on_delete=models.PROTECT,
        related_name="checkouts",
    )
    snapshot = models.ForeignKey(
        "ProjectSnapshot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="checkouts",
    )
    checked_out_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="checkouts",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    workspace_hint = models.CharField(max_length=500, blank=True)
    removed_paths = models.JSONField(default=list, blank=True)
    completed_revision = models.ForeignKey(
        Revision,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="completed_checkouts",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["part"],
                condition=models.Q(status="active"),
                name="unique_active_checkout_per_part",
            ),
        ]

    def __str__(self):
        return f"{self.part.number} {self.base_revision.revision_code} {self.status}"


class Annotation(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Offen"
        RESOLVED = "resolved", "Erledigt"

    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="annotations",
    )
    part = models.ForeignKey(
        Part,
        on_delete=models.PROTECT,
        related_name="annotations",
    )
    revision = models.ForeignKey(
        Revision,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="annotations",
    )
    object_name = models.CharField(max_length=200, blank=True)
    subelement = models.CharField(max_length=200, blank=True)
    text = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_annotations",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        target = self.object_name or self.part.number
        return f"{target}: {self.text[:60]}"


class ApiToken(TimeStampedModel):
    class Scope(models.TextChoices):
        READ = "read", "Lesen"
        WRITE = "write", "Schreiben"
        CHECKOUT = "checkout", "Checkout"
        ADMIN = "admin", "Admin"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_tokens",
    )
    name = models.CharField(max_length=120)
    token_prefix = models.CharField(max_length=24, unique=True)
    token_hash = models.CharField(max_length=64, unique=True)
    scopes = models.JSONField(default=list, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["user__username", "name"]

    def __str__(self):
        return f"{self.name} ({self.user})"

    @property
    def is_revoked(self):
        return self.revoked_at is not None

    def is_expired(self, at_time=None):
        if self.expires_at is None:
            return False
        return self.expires_at <= (at_time or timezone.now())

    def is_active(self, at_time=None):
        return not self.is_revoked and not self.is_expired(at_time=at_time)


class ProjectSnapshot(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="snapshots",
    )
    name = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_project_snapshots",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.project.code} - {self.name}"


class ProjectSnapshotEntry(models.Model):
    snapshot = models.ForeignKey(
        ProjectSnapshot,
        on_delete=models.CASCADE,
        related_name="entries",
    )
    path = models.CharField(max_length=500)
    revision = models.ForeignKey(
        Revision,
        on_delete=models.PROTECT,
        related_name="snapshot_entries",
    )

    class Meta:
        ordering = ["path"]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "path"],
                name="unique_path_per_project_snapshot",
            ),
        ]

    def __str__(self):
        return f"{self.path} -> {self.revision}"


class AuditEvent(models.Model):
    class Action(models.TextChoices):
        PROJECT_CREATED = "project_created", "Projekt angelegt"
        PROJECT_UPDATED = "project_updated", "Projekt geaendert"
        PROJECT_DELETED = "project_deleted", "Projekt geloescht"
        PART_CREATED = "part_created", "Teil angelegt"
        REVISION_UPLOADED = "revision_uploaded", "Revision hochgeladen"
        REVISION_RELEASED = "revision_released", "Revision freigegeben"
        REVISION_OBSOLETED = "revision_obsoleted", "Revision obsolet gesetzt"
        REVISION_DOWNLOADED = "revision_downloaded", "Revision heruntergeladen"
        REVISION_NOTES_UPDATED = "revision_notes_updated", "Revisionsnotiz geaendert"
        PROJECT_SNAPSHOT_CREATED = "project_snapshot_created", "Projektstand angelegt"
        EXPORT_JOB_CREATED = "export_job_created", "Exportjob angelegt"
        EXPORT_JOB_FAILED = "export_job_failed", "Exportjob fehlgeschlagen"
        REVISION_ARTIFACT_CREATED = "revision_artifact_created", "Revisionsartefakt angelegt"
        MANUFACTURING_FILE_UPLOADED = "manufacturing_file_uploaded", "Fertigungsdatei hochgeladen"
        MANUFACTURING_FILE_UPDATED = "manufacturing_file_updated", "Fertigungsdatei geaendert"
        MANUFACTURING_FILE_STATUS_CHANGED = "manufacturing_file_status_changed", "Fertigungsdatei-Status geaendert"
        MANUFACTURING_RUN_CREATED = "manufacturing_run_created", "Fertigungslauf angelegt"
        MANUFACTURING_RUN_ATTACHMENT_ADDED = "manufacturing_run_attachment_added", "Fertigungslauf-Anhang angelegt"
        CHECKOUT_CREATED = "checkout_created", "Checkout angelegt"
        CHECKOUT_FILE_REMOVED = "checkout_file_removed", "Teil aus Checkout entfernt"
        CHECKOUT_CANCELED = "checkout_canceled", "Checkout abgebrochen"
        CHECKOUT_COMPLETED = "checkout_completed", "Checkout eingecheckt"
        ANNOTATION_CREATED = "annotation_created", "Anmerkung angelegt"
        ANNOTATION_UPDATED = "annotation_updated", "Anmerkung geaendert"
        ANNOTATION_DELETED = "annotation_deleted", "Anmerkung geloescht"
        USER_CREATED = "user_created", "Benutzer angelegt"
        USER_UPDATED = "user_updated", "Benutzer geaendert"
        USER_PASSWORD_SET = "user_password_set", "Benutzerpasswort gesetzt"
        API_TOKEN_CREATED = "api_token_created", "API-Token angelegt"
        API_TOKEN_UPDATED = "api_token_updated", "API-Token geaendert"
        API_TOKEN_REVOKED = "api_token_revoked", "API-Token widerrufen"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=40, choices=Action.choices)
    object_repr = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.object_repr}"
