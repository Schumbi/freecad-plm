import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from .mesh_preview import render_stl_views
from .fcstd import fcstd_viewer_colors
from .models import AuditEvent, ExportJob, Revision, RevisionArtifact

logger = logging.getLogger(__name__)


PNG_VIEW_NAMES = (
    "front",
    "back",
    "left",
    "right",
    "top",
    "bottom",
    "isometric",
)


PREVIEW_GENERATOR_VERSION = 6


def preview_source_context(revision):
    """Identify and pin the same dependency set that the manifest exposes."""
    from .services.manifests import manifest_entries_for_revision
    from .services.snapshots import snapshot_entry_for_revision

    entry = snapshot_entry_for_revision(revision)
    if entry is None:
        return {}
    entries = manifest_entries_for_revision(revision, snapshot=entry.snapshot)
    sources = sorted((item["path"], item["revision"].sha256) for item in entries)
    return {
        "preview_snapshot_id": entry.snapshot_id,
        "preview_sources_sha256": sha256(json.dumps(sources).encode()).hexdigest(),
    }


def filter_preview_context(queryset, revision, *, artifacts=False):
    context = preview_source_context(revision)
    if context:
        prefix = "metadata__parameters" if artifacts else "parameters"
        queryset = queryset.filter(**{prefix + "__preview_sources_sha256": context["preview_sources_sha256"]})
    return queryset


FREECADCMD_SCRIPT = r'''
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import FreeCAD


def object_label(obj):
    return getattr(obj, "Label", "") or getattr(obj, "Name", "")


def has_solid_shape(obj):
    shape = getattr(obj, "Shape", None)
    if shape is None or getattr(shape, "isNull", lambda: True)():
        return False
    if getattr(shape, "Solids", None):
        return True
    return float(getattr(shape, "Volume", 0.0) or 0.0) > 1e-9


def is_exportable(obj):
    if hasattr(obj, "Visibility") and not obj.Visibility:
        return False
    return has_solid_shape(obj)


def exportable_objects(doc):
    candidates = [obj for obj in doc.Objects if is_exportable(obj)]
    candidate_ids = {id(obj) for obj in candidates}
    top_level = []
    for obj in candidates:
        has_exportable_parent = any(
            id(parent) in candidate_ids
            for parent in getattr(obj, "InList", [])
        )
        if not has_exportable_parent:
            top_level.append(obj)
    return top_level or candidates


def inspect_document(doc):
    objects = [
        {
            "name": obj.Name,
            "label": object_label(obj),
            "type": getattr(obj, "TypeId", ""),
            "visible": bool(getattr(obj, "Visibility", True)),
            "exportable": True,
        }
        for obj in exportable_objects(doc)
    ]
    varsets = []
    for obj in doc.Objects:
        type_id = getattr(obj, "TypeId", "")
        if type_id == "App::VarSet":
            properties = []
            for prop_name in obj.PropertiesList:
                if prop_name.startswith("_"):
                    continue
                try:
                    value = obj.getPropertyByName(prop_name)
                except Exception:
                    continue
                properties.append(
                    {
                        "name": prop_name,
                        "type": obj.getTypeIdOfProperty(prop_name),
                        "value": str(value),
                    }
                )
            varsets.append(
                {
                    "name": obj.Name,
                    "label": object_label(obj),
                    "properties": properties,
                }
            )
    return {"objects": objects, "varsets": varsets}


def selected_objects(doc, names):
    by_name = {obj.Name: obj for obj in doc.Objects}
    objects = [by_name[name] for name in names if name in by_name]
    if not objects:
        raise RuntimeError("Keine exportierbaren Objekte ausgewaehlt.")
    return objects


def export_objects(doc, spec, output_dir):
    export_format = spec["export_format"]
    names = spec.get("selected_objects", [])
    objects = selected_objects(doc, names)
    stem = f"{spec['revision_code']}-{export_format}"
    if export_format == "step":
        import Import
        path = output_dir / f"{stem}.step"
        Import.export(objects, str(path))
    elif export_format == "stl":
        import Mesh
        path = output_dir / f"{stem}.stl"
        Mesh.export(objects, str(path))
    elif export_format == "3mf":
        import Mesh
        path = output_dir / f"{stem}.3mf"
        Mesh.export(objects, str(path))
    else:
        raise RuntimeError(f"Unbekanntes Exportformat: {export_format}")
    return [{"path": str(path), "artifact_type": export_format, "view_name": ""}]


def preview_objects(doc):
    objects = exportable_objects(doc)
    if not objects:
        raise RuntimeError("Keine sichtbaren Volumenkoerper fuer Vorschau-Ansichten gefunden.")
    return objects


def write_viewer_3mf(meshes, colors, path):
    # Write explicit standard materials: Mesh.export in a headless process
    # cannot reliably recover colours stored by FreeCADGui.
    ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    ET.register_namespace("", ns)
    def node(parent, tag, **attrs):
        return ET.SubElement(parent, "{" + ns + "}" + tag, {k: str(v) for k, v in attrs.items()})
    model = ET.Element("{" + ns + "}model", {"unit": "millimeter"})
    resources = node(model, "resources")
    materials = node(resources, "basematerials", id=1)
    palette = list(dict.fromkeys(colors))
    for color in palette:
        node(materials, "base", name=color, displaycolor=color)
    build = node(model, "build")
    for index, (mesh, color) in enumerate(zip(meshes, colors), start=2):
        obj = node(resources, "object", id=index, type="model", name=mesh.Label,
                   pid=1, pindex=palette.index(color))
        geometry = node(obj, "mesh")
        vertices = node(geometry, "vertices")
        triangles = node(geometry, "triangles")
        points, facets = mesh.Mesh.Topology
        for point in points:
            node(vertices, "vertex", x=point.x, y=point.y, z=point.z)
        for facet in facets:
            node(triangles, "triangle", v1=facet[0], v2=facet[1], v3=facet[2])
        node(build, "item", objectid=index)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model", ET.tostring(model, encoding="utf-8", xml_declaration=True))
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')


def same_viewer_solid(solid, candidate):
    if solid.isSame(candidate):
        return True
    # Part::Compound can copy its children, losing OpenCascade identity.
    # Reject different bounds cheaply before checking coincident geometry.
    try:
        volume = float(solid.Volume)
        tolerance = max(volume * 1e-7, 1e-9)
        if abs(volume - float(candidate.Volume)) > tolerance:
            return False
        a, b = solid.BoundBox, candidate.BoundBox
        for key in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax"):
            if abs(float(getattr(a, key)) - float(getattr(b, key))) > 1e-7:
                return False
        if getattr(solid, "isPartner", lambda other: False)(candidate) is True:
            return True
        # Identical BREP copies need no expensive boolean intersection. This
        # matters for text inlays with thousands of faces and lost identity.
        serialize = getattr(solid, "exportBrepToString", None)
        other_serialize = getattr(candidate, "exportBrepToString", None)
        if callable(serialize) and callable(other_serialize):
            representation = serialize()
            if isinstance(representation, str) and representation == other_serialize():
                return True
        return abs(float(solid.common(candidate).Volume) - volume) <= tolerance
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return False


def linked_solid_color(root, solid, document_colors, fallback, path="", visited=None):
    # getSubObject applies all assembly/link placements, so compare geometry
    # in the root object's coordinates even across documents.
    visited = set() if visited is None else visited
    obj = root if not path else root.getSubObject(path, 1)
    if obj is None or (obj.Document.Name, obj.Name) in visited:
        return None
    visited = visited | {(obj.Document.Name, obj.Name)}
    colors = document_colors.get(str(Path(obj.Document.FileName).resolve()), {})
    color = colors.get(obj.Name, fallback)
    if getattr(obj, "TypeId", "") == "App::Link":
        linked = obj.getLinkedObject()
        linked_colors = document_colors.get(str(Path(linked.Document.FileName).resolve()), {})
        color = linked_colors.get(linked.Name, color)
    container = getattr(obj, "TypeId", "") in {
        "App::Link", "App::Part", "App::DocumentObjectGroup",
        "Assembly::AssemblyObject", "Part::Compound",
    }
    for sub in obj.getSubObjects() if container else []:
        child_path = path + sub
        found = linked_solid_color(root, solid, document_colors, color, child_path, visited)
        if found is not None:
            return found
    shape = getattr(obj, "Shape", None) if not path else root.getSubObject(path)
    if shape is not None:
        for candidate in getattr(shape, "Solids", []):
            if same_viewer_solid(solid, candidate):
                return color
    return None


def solid_viewer_color(obj, solid, colors, fallback="#8193A1", document_colors=None):
    # Compounds may contain separately coloured child objects. Keep their
    # identities where OpenCascade can match the constituent solids.
    color = colors.get(obj.Name, fallback)
    if document_colors and hasattr(obj, "getSubObject"):
        found = linked_solid_color(obj, solid, document_colors, color)
        if found is not None:
            return found
    if getattr(obj, "TypeId", "") == "Part::Compound":
        for child in getattr(obj, "OutList", []):
            for child_solid in getattr(getattr(child, "Shape", None), "Solids", []):
                if same_viewer_solid(solid, child_solid):
                    return solid_viewer_color(child, child_solid, colors, color)
    return color


def export_viewer_preview(objects, path, colors=None, document_colors=None):
    # Keep solids separate, including flush inlays inside assembly compounds.
    # A temporary document avoids modifying the source or its feature history.
    import MeshPart

    preview_doc = FreeCAD.newDocument("PLMViewerPreview")
    try:
        meshes = []
        mesh_colors = []
        for obj in objects:
            for index, solid in enumerate(obj.Shape.Solids):
                mesh = preview_doc.addObject("Mesh::Feature", "PreviewSolid")
                mesh.Label = f"{object_label(obj)} / {index + 1}"
                mesh.Mesh = MeshPart.meshFromShape(
                    Shape=solid, LinearDeflection=0.03,
                    AngularDeflection=0.1, Relative=False,
                )
                meshes.append(mesh)
                mesh_colors.append(solid_viewer_color(obj, solid, colors or {}, document_colors=document_colors))
        if not meshes:
            raise RuntimeError("Keine Volumenkoerper fuer die 3D-Vorschau gefunden.")
        write_viewer_3mf(meshes, mesh_colors, path)
    finally:
        FreeCAD.closeDocument(preview_doc.Name)


def create_preview_sources(doc, spec, output_dir):
    objects = preview_objects(doc)

    import Import
    import Mesh

    step_path = output_dir / f"{spec['revision_code']}-preview.step"
    stl_path = output_dir / f"{spec['revision_code']}-preview.stl"
    Import.export(objects, str(step_path))
    Mesh.export(objects, str(stl_path))
    viewer_path = output_dir / f"{spec['revision_code']}-viewer.3mf"
    export_viewer_preview(objects, viewer_path, spec.get("viewer_colors", {}), spec.get("viewer_document_colors", {}))
    return {
        "artifacts": [
            {"path": str(step_path), "artifact_type": "step", "view_name": "preview"},
            {"path": str(viewer_path), "artifact_type": "3mf", "view_name": "viewer-preview"},
        ],
        "preview_mesh_path": str(stl_path),
    }


def main():
    spec_path = Path(sys.argv[1])
    result_path = Path(sys.argv[2])
    spec = json.loads(spec_path.read_text())
    output_dir = Path(spec["output_dir"])
    doc = FreeCAD.openDocument(spec["fcstd_path"])
    doc.recompute()

    result = {"metadata": inspect_document(doc), "artifacts": []}
    if spec["job_type"] == "export":
        result["artifacts"] = export_objects(doc, spec, output_dir)
    elif spec["job_type"] == "png_views":
        result.update(create_preview_sources(doc, spec, output_dir))
    elif spec["job_type"] != "inspect":
        raise RuntimeError(f"Unbekannter Job-Typ: {spec['job_type']}")

    result_path.write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
'''


FREECADCMD_BOOTSTRAP = (
    "import sys; "
    "sys.argv = [sys.argv[-3], sys.argv[-2], sys.argv[-1]]; "
    "path = sys.argv[0]; "
    "exec(compile(open(path, 'rb').read(), path, 'exec'), "
    "{'__name__': '__main__', '__file__': path})"
)


def create_export_job(
    *,
    revision,
    job_type,
    created_by,
    export_format="",
    selected_objects=None,
    parameters=None,
):
    parameters = dict(parameters or {})
    if job_type == ExportJob.JobType.PNG_VIEWS:
        parameters.update(preview_source_context(revision))
    job = ExportJob.objects.create(
        revision=revision,
        job_type=job_type,
        export_format=export_format,
        selected_objects=selected_objects or [],
        parameters=parameters or {},
        created_by=created_by,
    )
    AuditEvent.objects.create(
        actor=created_by,
        action=AuditEvent.Action.EXPORT_JOB_CREATED,
        object_repr=str(job),
        metadata={
            "revision_id": revision.id,
            "job_id": job.id,
            "job_type": job.job_type,
            "export_format": job.export_format,
            "selected_objects": job.selected_objects,
        },
    )
    return job


def queued_export_jobs(limit=None):
    queryset = ExportJob.objects.filter(status=ExportJob.Status.QUEUED).order_by(
        "created_at"
    )
    if limit:
        queryset = queryset[:limit]
    return list(queryset.select_related("revision", "revision__part", "created_by"))


def export_job_stale_seconds():
    configured = getattr(settings, "EXPORT_JOB_STALE_SECONDS", None)
    if configured is not None:
        return configured
    timeout = getattr(settings, "FREECADCMD_TIMEOUT_SECONDS", 300)
    return max(timeout + 120, 600)


def recover_stale_export_jobs(now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=export_job_stale_seconds())
    stale_jobs = list(
        ExportJob.objects.filter(
            status=ExportJob.Status.RUNNING,
            started_at__lt=cutoff,
        ).select_related("revision", "created_by")
    )
    stale_message = (
        "Job blieb zu lange im Status running haengen "
        f"(>{export_job_stale_seconds()}s). "
        "Vermutlich Worker-Neustart oder abgebrochener FreeCAD-Prozess."
    )
    for job in stale_jobs:
        job.status = ExportJob.Status.FAILED
        job.error = stale_message
        job.finished_at = now
        job.save(update_fields=["status", "error", "finished_at", "updated_at"])
        AuditEvent.objects.create(
            actor=job.created_by,
            action=AuditEvent.Action.EXPORT_JOB_FAILED,
            object_repr=str(job),
            metadata={
                "revision_id": job.revision_id,
                "job_id": job.id,
                "job_type": job.job_type,
                "error": job.error,
                "recovered_stale": True,
            },
        )
    if stale_jobs:
        logger.warning(
            "Marked %s stale export job(s) as failed.",
            len(stale_jobs),
        )
    return stale_jobs


def process_queued_export_jobs(limit=None):
    recover_stale_export_jobs()
    processed = []
    for job in queued_export_jobs(limit=limit):
        processed.append(process_export_job(job))
    return processed


def process_export_job(job):
    job.status = ExportJob.Status.RUNNING
    job.started_at = timezone.now()
    job.error = ""
    job.save(update_fields=["status", "started_at", "error", "updated_at"])

    try:
        result = run_freecadcmd_job(job)
        apply_freecadcmd_result(job, result)
    except Exception as exc:
        job.status = ExportJob.Status.FAILED
        job.error = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at", "updated_at"])
        AuditEvent.objects.create(
            actor=job.created_by,
            action=AuditEvent.Action.EXPORT_JOB_FAILED,
            object_repr=str(job),
            metadata={
                "revision_id": job.revision_id,
                "job_id": job.id,
                "job_type": job.job_type,
                "error": job.error,
            },
        )
    return job


def run_freecadcmd_job(job):
    timeout = getattr(settings, "FREECADCMD_TIMEOUT_SECONDS", 300)

    with TemporaryDirectory() as temp_dir:
        workdir = Path(temp_dir)
        fcstd_path = stage_revision_inputs(job, workdir)

        script_path = workdir / "plm_freecadcmd_job.py"
        spec_path = workdir / "job_spec.json"
        result_path = workdir / "job_result.json"
        output_dir = workdir / "output"
        output_dir.mkdir()

        if job.revision.file_format == Revision.FileFormat.STL:
            if job.job_type != ExportJob.JobType.PNG_VIEWS:
                raise RuntimeError(
                    "Für primäre STL-Dateien sind nur Vorschau-Ansichten verfügbar."
                )
            artifacts = render_stl_views(
                fcstd_path,
                output_dir,
                job.revision.revision_code,
                width=getattr(settings, "PREVIEW_PNG_WIDTH", 400),
                height=getattr(settings, "PREVIEW_PNG_HEIGHT", 300),
            )
            for artifact in artifacts:
                path = Path(artifact["path"])
                artifact["filename"] = path.name
                artifact["content"] = path.read_bytes()
            return {"metadata": {}, "artifacts": artifacts}

        script_path.write_text(FREECADCMD_SCRIPT, encoding="utf-8")
        spec_path.write_text(
            json.dumps(
                {
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "revision_code": job.revision.revision_code,
                    "fcstd_path": str(fcstd_path),
                    "output_dir": str(output_dir),
                    "export_format": job.export_format,
                    "selected_objects": job.selected_objects,
                    "parameters": job.parameters,
                    "viewer_colors": fcstd_viewer_colors(fcstd_path)
                    if job.revision.file_format == Revision.FileFormat.FCSTD
                    and job.job_type == ExportJob.JobType.PNG_VIEWS else {},
                    "viewer_document_colors": {
                        str(path.resolve()): fcstd_viewer_colors(path)
                        for path in workdir.rglob("*")
                        if path.suffix.lower() == ".fcstd"
                    } if job.job_type == ExportJob.JobType.PNG_VIEWS else {},
                }
            ),
            encoding="utf-8",
        )

        command = freecadcmd_command(job)
        # FreeCAD 1.0 legt beim Start sein User-Konfigverzeichnis unter $HOME an
        # und segfaultet, wenn HOME fehlt oder nicht beschreibbar ist (z.B. im
        # gehaerteten Worker mit read-only Root-FS). Das beschreibbare, pro Job
        # eindeutige Temp-Verzeichnis als HOME vermeidet das.
        run_env = {**os.environ, "HOME": str(workdir)}
        completed = subprocess.run(
            [
                *command,
                "-c",
                FREECADCMD_BOOTSTRAP,
                "--pass",
                str(script_path),
                str(spec_path),
                str(result_path),
            ],
            cwd=workdir,
            env=run_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        log_header = "\n".join(
            [
                "Command: " + shlex.join(command),
                "DISPLAY: " + str(os.environ.get("DISPLAY", "")),
                "XAUTHORITY: " + str(os.environ.get("XAUTHORITY", "")),
            ]
        )
        job.log = "\n".join(
            item for item in (log_header, completed.stdout, completed.stderr) if item
        )
        job.save(update_fields=["log", "updated_at"])

        if not result_path.exists():
            if completed.returncode != 0:
                raise RuntimeError(
                    f"FreeCADCmd endete mit Code {completed.returncode}."
                )
            raise RuntimeError("FreeCADCmd hat kein Ergebnis geschrieben.")

        result = json.loads(result_path.read_text(encoding="utf-8"))
        preview_mesh_path = result.pop("preview_mesh_path", "")
        if preview_mesh_path:
            result.setdefault("artifacts", []).extend(
                render_stl_views(
                    preview_mesh_path,
                    output_dir,
                    job.revision.revision_code,
                    width=getattr(settings, "PREVIEW_PNG_WIDTH", 400),
                    height=getattr(settings, "PREVIEW_PNG_HEIGHT", 300),
                )
            )
        for artifact in result.get("artifacts", []):
            path = Path(artifact["path"])
            artifact["filename"] = path.name
            artifact["content"] = path.read_bytes()
        return result


def stage_revision_inputs(job, workdir):
    # Lokaler Import vermeidet einen Modulzyklus: services.checkouts startet
    # seinerseits Ableitungsjobs ueber plm.derivatives/freecadcmd.
    from .services.manifests import manifest_entries_for_revision

    root_revision = job.revision
    root_entries = (
        root_revision.snapshot_entries.select_related("snapshot")
    )
    snapshot_id = job.parameters.get("preview_snapshot_id")
    root_entry = (root_entries.filter(snapshot_id=snapshot_id).first() if snapshot_id
                  else root_entries.order_by("-snapshot__created_at", "path").first())
    if snapshot_id and root_entry is None:
        raise RuntimeError("Der Projektstand des Vorschau-Jobs ist nicht mehr verfügbar.")
    snapshot = root_entry.snapshot if root_entry else None
    entries = manifest_entries_for_revision(root_revision, snapshot=snapshot)
    root_path = None
    for entry in entries:
        target_path = workdir / Path(entry["path"])
        copy_revision_file(entry["revision"], target_path)
        if entry["is_root"]:
            root_path = target_path

    if root_path is None:
        raise RuntimeError("Die Hauptdatei fehlt im Projektstand des FreeCAD-Jobs.")
    return root_path


def copy_revision_file(revision, target_path):
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with revision.file.open("rb") as source:
        target_path.write_bytes(source.read())


def freecadcmd_command(job=None):
    configured = getattr(
        settings,
        "FREECADCMD_COMMAND",
        getattr(settings, "FREECADCMD_PATH", "FreeCADCmd"),
    )
    return configured_command(configured, "FreeCADCmd", job)


def configured_command(configured, label, job=None):
    if isinstance(configured, (list, tuple)):
        command = [str(item) for item in configured]
    else:
        command = shlex.split(str(configured), posix=os.name != "nt")
    if not command:
        raise RuntimeError(f"{label} ist nicht konfiguriert.")

    executable = command[0]
    command = with_flatpak_worker_options(command)
    if Path(executable).suffix.lower() == ".py" and Path(executable).exists():
        return [sys.executable, *command]
    if shutil.which(executable) or Path(executable).exists():
        return command

    flatpak_command = [
        "flatpak",
        "run",
        "--filesystem=/tmp",
        "--branch=stable",
        "--arch=x86_64",
        "--command=FreeCADCmd",
        "org.freecad.FreeCAD",
    ]
    if configured == "FreeCADCmd" and shutil.which("flatpak"):
        return flatpak_command

    raise RuntimeError(f"{label} wurde nicht gefunden: {configured}")


def with_flatpak_worker_options(command):
    if len(command) < 2 or command[0] != "flatpak" or command[1] != "run":
        return command
    options = []
    if not any(item.startswith("--filesystem=") or item == "--filesystem" for item in command):
        options.append("--filesystem=/tmp")
    if not options:
        return command
    return [command[0], command[1], *options, *command[2:]]


@transaction.atomic
def apply_freecadcmd_result(job, result):
    metadata = result.get("metadata") or {}
    if metadata:
        revision_metadata = job.revision.extracted_metadata or {}
        revision_metadata["freecadcmd"] = metadata
        job.revision.extracted_metadata = revision_metadata
        job.revision.save(update_fields=["extracted_metadata", "updated_at"])

    for artifact_data in result.get("artifacts", []):
        content = artifact_data["content"]
        digest = sha256(content).hexdigest()
        artifact_metadata = {
            "job_id": job.id,
            "selected_objects": job.selected_objects,
            "parameters": job.parameters,
        }
        if job.job_type == ExportJob.JobType.PNG_VIEWS:
            artifact_metadata["preview_generator_version"] = PREVIEW_GENERATOR_VERSION
        artifact = RevisionArtifact.objects.create(
            revision=job.revision,
            job=job,
            artifact_type=artifact_data["artifact_type"],
            view_name=artifact_data.get("view_name", ""),
            file=ContentFile(content, name=artifact_data["filename"]),
            original_filename=artifact_data["filename"],
            sha256=digest,
            size_bytes=len(content),
            metadata=artifact_metadata,
        )
        AuditEvent.objects.create(
            actor=job.created_by,
            action=AuditEvent.Action.REVISION_ARTIFACT_CREATED,
            object_repr=str(artifact),
            metadata={
                "revision_id": job.revision_id,
                "job_id": job.id,
                "artifact_id": artifact.id,
                "artifact_type": artifact.artifact_type,
                "view_name": artifact.view_name,
                "sha256": artifact.sha256,
            },
        )

    job.status = ExportJob.Status.SUCCEEDED
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "finished_at", "updated_at"])
    return job
