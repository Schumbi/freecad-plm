import json
import os
import shlex
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from .models import AuditEvent, ExportJob, RevisionArtifact


PNG_VIEW_NAMES = (
    "front",
    "back",
    "left",
    "right",
    "top",
    "bottom",
    "isometric",
)


FREECADCMD_SCRIPT = r'''
import json
import math
import sys
from pathlib import Path

import FreeCAD


EXPORTABLE_TYPE_MARKERS = ("Part::", "PartDesign::", "Mesh::")


def object_label(obj):
    return getattr(obj, "Label", "") or getattr(obj, "Name", "")


def is_exportable(obj):
    if hasattr(obj, "Visibility") and not obj.Visibility:
        return False
    type_id = getattr(obj, "TypeId", "")
    shape = getattr(obj, "Shape", None)
    if shape is not None and not getattr(shape, "isNull", lambda: True)():
        return True
    return type_id.startswith(EXPORTABLE_TYPE_MARKERS)


def inspect_document(doc):
    objects = []
    varsets = []
    for obj in doc.Objects:
        type_id = getattr(obj, "TypeId", "")
        if is_exportable(obj):
            objects.append(
                {
                    "name": obj.Name,
                    "label": object_label(obj),
                    "type": type_id,
                    "visible": bool(getattr(obj, "Visibility", True)),
                    "exportable": True,
                }
            )
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


def create_png_views(doc, spec, output_dir):
    import FreeCADGui as Gui

    view = Gui.ActiveDocument.ActiveView
    view_methods = {
        "front": "viewFront",
        "back": "viewRear",
        "left": "viewLeft",
        "right": "viewRight",
        "top": "viewTop",
        "bottom": "viewBottom",
        "isometric": "viewIsometric",
    }
    artifacts = []
    for name, method_name in view_methods.items():
        getattr(view, method_name)()
        view.fitAll()
        path = output_dir / f"{spec['revision_code']}-{name}.png"
        view.saveImage(str(path), 1600, 1200, "White")
        artifacts.append({"path": str(path), "artifact_type": "png", "view_name": name})
    return artifacts


def main():
    spec_path = Path(sys.argv[1])
    result_path = Path(sys.argv[2])
    spec = json.loads(spec_path.read_text())
    output_dir = Path(spec["output_dir"])
    if spec["job_type"] == "png_views":
        try:
            import FreeCADGui as Gui
        except Exception as exc:
            raise RuntimeError("PNG-Ansichten benoetigen FreeCADGui-Unterstuetzung.") from exc
        Gui.showMainWindow()
        doc = FreeCAD.openDocument(spec["fcstd_path"])
        try:
            Gui.activateWorkbench("PartWorkbench")
        except Exception:
            pass
        Gui.updateGui()
        if Gui.ActiveDocument is None:
            Gui.getDocument(doc.Name)
    else:
        doc = FreeCAD.openDocument(spec["fcstd_path"])
    doc.recompute()

    result = {"metadata": inspect_document(doc), "artifacts": []}
    if spec["job_type"] == "export":
        result["artifacts"] = export_objects(doc, spec, output_dir)
    elif spec["job_type"] == "png_views":
        result["artifacts"] = create_png_views(doc, spec, output_dir)
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


def process_queued_export_jobs(limit=None):
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
        fcstd_path = workdir / job.revision.original_filename
        with job.revision.file.open("rb") as source:
            fcstd_path.write_bytes(source.read())

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
        for artifact in result.get("artifacts", []):
            path = Path(artifact["path"])
            artifact["filename"] = path.name
            artifact["content"] = path.read_bytes()
        return result


def freecadcmd_command(job=None):
    configured = getattr(
        settings,
        "FREECADCMD_COMMAND",
        getattr(settings, "FREECADCMD_PATH", "FreeCADCmd"),
    )
    if isinstance(configured, (list, tuple)):
        command = [str(item) for item in configured]
    else:
        command = shlex.split(str(configured))
    if not command:
        raise RuntimeError("FreeCADCmd ist nicht konfiguriert.")

    executable = command[0]
    command = with_flatpak_worker_options(command)
    command = with_png_gui_command(command, job)
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

    raise RuntimeError(f"FreeCADCmd wurde nicht gefunden: {configured}")


def with_flatpak_worker_options(command):
    if len(command) < 2 or command[0] != "flatpak" or command[1] != "run":
        return command
    options = []
    if not any(item.startswith("--filesystem=") or item == "--filesystem" for item in command):
        options.append("--filesystem=/tmp")
    if not options:
        return command
    return [command[0], command[1], *options, *command[2:]]


def with_png_gui_command(command, job):
    if not job or job.job_type != ExportJob.JobType.PNG_VIEWS:
        return command

    updated = list(command)
    for index, item in enumerate(updated):
        if item == "--command=FreeCADCmd":
            updated[index] = "--command=FreeCAD"
            return updated
        if item == "--command" and index + 1 < len(updated) and updated[index + 1] == "FreeCADCmd":
            updated[index + 1] = "FreeCAD"
            return updated

    executable = Path(updated[0])
    if executable.name == "FreeCADCmd":
        sibling = executable.with_name("FreeCAD")
        if sibling.exists():
            updated[0] = str(sibling)
        elif shutil.which("FreeCAD"):
            updated[0] = "FreeCAD"
    return updated


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
        artifact = RevisionArtifact.objects.create(
            revision=job.revision,
            job=job,
            artifact_type=artifact_data["artifact_type"],
            view_name=artifact_data.get("view_name", ""),
            file=ContentFile(content, name=artifact_data["filename"]),
            original_filename=artifact_data["filename"],
            sha256=digest,
            size_bytes=len(content),
            metadata={
                "job_id": job.id,
                "selected_objects": job.selected_objects,
                "parameters": job.parameters,
            },
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
