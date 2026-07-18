"""Fachliche PLM-Services, aufgeteilt in thematische Submodule.

Diese Fassade re-exportiert alle oeffentlichen Namen, damit bestehende
Importe wie ``from plm.services import ...`` unveraendert funktionieren.
"""
from .common import (
    PLMRevisionConflict,
    ProjectZipMember,
    safe_snapshot_path,
    upload_file_digest,
)
from .manufacturing import (
    MANUFACTURING_FILE_EXTENSIONS,
    create_manufacturing_file_from_upload,
    decimal_config_value,
    decode_config_bytes,
    extract_slicer_fields,
    first_config_value,
    flatten_config_value,
    infer_manufacturing_file_type,
    inspect_manufacturing_upload,
    int_config_value,
    json_safe_value,
    parse_slicer_config,
    parse_slicer_xml_config,
    select_3mf_thumbnail_name,
    slicer_config_priority,
    thumbnail_candidate_score,
    unique_values,
)
from .revisions import (
    REVISION_CODE_MAX_NUMBER,
    REVISION_CODE_NUMBER_WIDTH,
    REVISION_CODE_PATTERN,
    REVISION_CODE_PREFIX,
    create_annotation,
    create_or_reuse_revision,
    create_revision_from_upload,
    existing_revision_for_upload_hash,
    fcstd_model_changed,
    format_revision_code,
    freecad_plm_revision,
    next_part_number,
    next_revision_code,
    obsolete_revision,
    part_category_from_metadata,
    part_identity_from_metadata,
    release_revision,
    revision_code_number,
    revision_document_signature,
    revision_metadata_from_validation,
    uploaded_document_signature,
    validate_revision_code_argument,
)
from .snapshots import (
    SNAPSHOT_VERSION_SUFFIX_RE,
    checkout_snapshot_name,
    create_snapshot_from_checkout_revisions,
    delete_project_tree,
    import_project_snapshot,
    iter_fcstd_zip_members,
    resolve_reference_path,
    revision_reference_files,
    snapshot_base_name,
    snapshot_entries_with_references,
    snapshot_entry_for_revision,
)
from .manifests import (
    checkout_manifest,
    manifest_entries_by_path,
    manifest_entries_for_checkout,
    manifest_entries_for_revision,
    manifest_file_payload,
    revision_manifest,
)
from .checkouts import (
    cancel_checkout,
    checkin_checkout,
    checkin_checkout_files,
    complete_checkout,
    create_checkout,
    remove_checkout_file,
)
from .search import (
    PLM_SEARCH_RESULT_LIMIT,
    PlmSearchResults,
    search_plm,
)
