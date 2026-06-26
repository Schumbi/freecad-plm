from django.contrib import admin
from .models import AuditEvent, Part, Project, Revision


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_archived", "created_at", "updated_at")
    list_filter = ("is_archived",)
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
        "sha256",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "object_repr")
    list_filter = ("action",)
    search_fields = ("object_repr", "actor__username")
    readonly_fields = ("created_at",)
