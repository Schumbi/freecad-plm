from django.contrib import admin
from .models import (
    Annotation,
    AuditEvent,
    Checkout,
    ExportJob,
    ManufacturingFile,
    ManufacturingMachine,
    ManufacturingRun,
    ManufacturingRunAttachment,
    Part,
    Project,
    ProjectSnapshot,
    ProjectSnapshotEntry,
    Revision,
    RevisionArtifact,
)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "status", "project_date", "is_archived", "created_at", "updated_at")
    list_filter = ("status", "is_archived")
    search_fields = ("code", "name", "description")


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ("number", "name", "project", "category", "is_archived")
    list_filter = ("category", "is_archived", "project")
    search_fields = ("number", "name", "description", "material", "supplier", "tags")


@admin.register(Revision)
class RevisionAdmin(admin.ModelAdmin):
    list_display = (
        "part",
        "revision_code",
        "status",
        "original_filename",
        "size_bytes",
        "created_by",
        "created_at",
    )
    list_filter = ("status", "part__project")
    search_fields = (
        "part__number",
        "part__name",
        "revision_code",
        "original_filename",
        "notes",
        "sha256",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(ExportJob)
class ExportJobAdmin(admin.ModelAdmin):
    list_display = (
        "revision",
        "job_type",
        "export_format",
        "status",
        "created_by",
        "created_at",
        "finished_at",
    )
    list_filter = ("job_type", "status", "export_format")
    search_fields = ("revision__part__number", "revision__revision_code", "error", "log")
    readonly_fields = ("created_at", "updated_at", "started_at", "finished_at")


@admin.register(RevisionArtifact)
class RevisionArtifactAdmin(admin.ModelAdmin):
    list_display = (
        "revision",
        "artifact_type",
        "view_name",
        "original_filename",
        "size_bytes",
        "created_at",
    )
    list_filter = ("artifact_type",)
    search_fields = ("revision__part__number", "revision__revision_code", "original_filename")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ManufacturingMachine)
class ManufacturingMachineAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "machine_type",
        "manufacturer",
        "model",
        "integration_kind",
        "is_active",
    )
    list_filter = ("machine_type", "manufacturer", "is_active")
    search_fields = ("name", "manufacturer", "model", "serial_number", "network_address")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ManufacturingFile)
class ManufacturingFileAdmin(admin.ModelAdmin):
    list_display = (
        "revision",
        "label",
        "file_type",
        "purpose",
        "status",
        "machine",
        "slicer_name",
        "material",
        "created_at",
    )
    list_filter = ("file_type", "purpose", "status", "machine")
    search_fields = (
        "revision__part__number",
        "revision__part__name",
        "revision__revision_code",
        "label",
        "original_filename",
        "sha256",
    )
    readonly_fields = ("created_at", "updated_at", "storage_key", "sha256", "size_bytes")


class ManufacturingRunAttachmentInline(admin.TabularInline):
    model = ManufacturingRunAttachment
    extra = 0
    readonly_fields = ("created_at", "updated_at", "sha256", "size_bytes")


@admin.register(ManufacturingRun)
class ManufacturingRunAdmin(admin.ModelAdmin):
    list_display = (
        "manufacturing_file",
        "machine",
        "status",
        "operator",
        "quantity",
        "started_at",
        "finished_at",
    )
    list_filter = ("status", "machine")
    search_fields = (
        "manufacturing_file__revision__part__number",
        "manufacturing_file__label",
        "operator__username",
    )
    readonly_fields = ("created_at", "updated_at")
    inlines = (ManufacturingRunAttachmentInline,)


@admin.register(ManufacturingRunAttachment)
class ManufacturingRunAttachmentAdmin(admin.ModelAdmin):
    list_display = ("run", "attachment_type", "original_filename", "size_bytes", "created_at")
    list_filter = ("attachment_type",)
    search_fields = ("run__manufacturing_file__label", "original_filename", "sha256")
    readonly_fields = ("created_at", "updated_at", "sha256", "size_bytes")


@admin.register(Checkout)
class CheckoutAdmin(admin.ModelAdmin):
    list_display = (
        "part",
        "base_revision",
        "snapshot",
        "status",
        "checked_out_by",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "part__project")
    search_fields = ("part__number", "part__name", "checked_out_by__username")
    readonly_fields = ("created_at", "updated_at", "completed_at", "canceled_at")


@admin.register(Annotation)
class AnnotationAdmin(admin.ModelAdmin):
    list_display = (
        "part",
        "revision",
        "object_name",
        "status",
        "created_by",
        "created_at",
    )
    list_filter = ("status", "project")
    search_fields = (
        "part__number",
        "part__name",
        "revision__revision_code",
        "object_name",
        "text",
    )
    readonly_fields = ("created_at", "updated_at")


class ProjectSnapshotEntryInline(admin.TabularInline):
    model = ProjectSnapshotEntry
    extra = 0
    readonly_fields = ("path", "revision")
    can_delete = False


@admin.register(ProjectSnapshot)
class ProjectSnapshotAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "created_by", "created_at")
    list_filter = ("project",)
    search_fields = ("name", "project__code", "project__name")
    readonly_fields = ("created_at",)
    inlines = (ProjectSnapshotEntryInline,)


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "object_repr")
    list_filter = ("action",)
    search_fields = ("object_repr", "actor__username")
    readonly_fields = ("created_at",)
