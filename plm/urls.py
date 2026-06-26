from django.urls import path

from . import views

app_name = "plm"

urlpatterns = [
    path("", views.project_list, name="project_list"),
    path("projects/new/", views.create_project, name="create_project"),
    path("projects/<int:project_id>/", views.project_detail, name="project_detail"),
    path(
        "projects/<int:project_id>/snapshots/upload/",
        views.upload_project_snapshot,
        name="upload_project_snapshot",
    ),
    path("projects/<int:project_id>/parts/new/", views.create_part, name="create_part"),
    path("parts/<int:part_id>/", views.part_detail, name="part_detail"),
    path("parts/<int:part_id>/upload/", views.upload_revision, name="upload_revision"),
    path(
        "parts/<int:part_id>/upload/confirm/",
        views.confirm_revision_upload,
        name="confirm_revision_upload",
    ),
    path(
        "revisions/<int:revision_id>/download/",
        views.download_revision,
        name="download_revision",
    ),
    path(
        "revisions/<int:revision_id>/release/",
        views.release_revision_view,
        name="release_revision",
    ),
    path(
        "revisions/<int:revision_id>/notes/",
        views.update_revision_notes,
        name="update_revision_notes",
    ),
    path(
        "snapshots/<int:snapshot_id>/download/",
        views.download_project_snapshot,
        name="download_project_snapshot",
    ),
]
