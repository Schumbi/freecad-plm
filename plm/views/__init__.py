"""View-Schicht, aufgeteilt in thematische Submodule.

Die Fassade re-exportiert alle View-Callables, damit ``plm/urls.py``
(``views.<name>``) unveraendert funktioniert.
"""
from .common import (
    EXPORT_JOB_ACTIVE_STATUSES,
    PENDING_REVISION_UPLOAD_SESSION_KEY,
    VIEWER_CONTENT_TYPES,
    VIEWER_FALLBACK_VIEW_NAME,
    VIEWER_PREVIEW_VIEW_NAME,
    VIEWER_SUPPORTED_ARTIFACT_TYPES,
    VIEWER_SUPPORTED_MANUFACTURING_TYPES,
    active_admin_count,
    admin_required_response,
    build_revision_compare_pairs,
    clear_pending_revision_upload,
    ensure_revision_viewer_preview,
    missing_viewer_preview_response,
    referenced_revision_zip_response,
    revision_png_status_needs_poll,
    revision_png_status_payload,
    revision_viewer_artifact,
    save_pending_revision_upload,
    snapshot_entry_for_revision_download,
    token_status,
    validate_user_admin_safety,
    viewer_file_format,
    viewer_file_response,
    viewer_status_payload,
)
from .jobs import (
    EXPORT_JOB_RECENT_MINUTES,
    export_job_payload,
    user_export_jobs_status,
)
from .users import (
    create_user,
    create_user_token,
    edit_api_token,
    edit_user,
    logout_view,
    revoke_api_token,
    set_user_password,
    user_management_list,
)
from .projects import (
    create_project,
    delete_project,
    download_project_snapshot,
    edit_project,
    global_search,
    project_detail,
    project_list,
    project_properties,
    upload_project_snapshot,
)
from .parts import (
    create_part,
    part_detail,
    part_properties,
    process_export_jobs_once,
)
from .revisions import (
    artifact_viewer_source,
    confirm_revision_upload,
    create_revision_export_job,
    create_revision_inspect_job,
    create_revision_png_job,
    create_revision_viewer_preview,
    download_revision,
    download_revision_artifact,
    obsolete_revision_view,
    release_revision_view,
    revision_compare,
    revision_compare_status,
    revision_properties,
    revision_viewer_source,
    revision_viewer_status,
    update_revision_notes,
    upload_revision,
)
from .manufacturing import (
    download_manufacturing_file,
    manufacturing_file_thumbnail,
    manufacturing_file_viewer_source,
    obsolete_manufacturing_file,
    upload_manufacturing_file,
)
