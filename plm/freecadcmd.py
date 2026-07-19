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
from .models import AuditEvent, ExportJob, RevisionArtifact

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


PREVIEW_GENERATOR_VERSION = 3


FREECADCMD_SCRIPT = r'''
import json
import sys
from pathlib import Path

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


def create_preview_sources(doc, spec, output_dir):
    objects = preview_objects(doc)

    import Import
    import Mesh

    step_path = output_dir / f"{spec['revision_code']}-preview.step"
    stl_path = output_dir / f"{spec['revision_code']}-preview.stl"
    Import.export(objects, str(step_path))
    Mesh.export(objects, str(stl_path))
    return {
        "artifacts": [{"path": str(step_path), "artifact_type": "step", "view_name": "preview"}],
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
            preview_mesh = Path(preview_mesh_path)
            result.setdefault("artifacts", []).append(
                {
                    "path": str(preview_mesh),
                    "artifact_type": "stl",
                    "view_name": "viewer-preview",
                }
            )
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
    root_entry = (
        root_revision.snapshot_entries.select_related("snapshot")
        .order_by("snapshot__created_at", "id")
        .first()
    )
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
