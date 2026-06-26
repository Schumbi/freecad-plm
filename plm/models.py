from django.db import models
from django.conf import settings


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Project(TimeStampedModel):
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
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
        PART_CREATED = "part_created", "Teil angelegt"
        REVISION_UPLOADED = "revision_uploaded", "Revision hochgeladen"
        REVISION_RELEASED = "revision_released", "Revision freigegeben"
        REVISION_DOWNLOADED = "revision_downloaded", "Revision heruntergeladen"
        REVISION_NOTES_UPDATED = "revision_notes_updated", "Revisionsnotiz geaendert"
        PROJECT_SNAPSHOT_CREATED = "project_snapshot_created", "Projektstand angelegt"

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
