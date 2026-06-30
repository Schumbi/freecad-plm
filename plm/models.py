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
        REVISION_DOWNLOADED = "revision_downloaded", "Revision heruntergeladen"
        REVISION_NOTES_UPDATED = "revision_notes_updated", "Revisionsnotiz geaendert"
        PROJECT_SNAPSHOT_CREATED = "project_snapshot_created", "Projektstand angelegt"
        EXPORT_JOB_CREATED = "export_job_created", "Exportjob angelegt"
        EXPORT_JOB_FAILED = "export_job_failed", "Exportjob fehlgeschlagen"
        REVISION_ARTIFACT_CREATED = "revision_artifact_created", "Revisionsartefakt angelegt"
        CHECKOUT_CREATED = "checkout_created", "Checkout angelegt"
        CHECKOUT_CANCELED = "checkout_canceled", "Checkout abgebrochen"
        CHECKOUT_COMPLETED = "checkout_completed", "Checkout eingecheckt"
        ANNOTATION_CREATED = "annotation_created", "Anmerkung angelegt"
        ANNOTATION_UPDATED = "annotation_updated", "Anmerkung geaendert"

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
