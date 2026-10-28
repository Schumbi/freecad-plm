from django.core.exceptions import ValidationError

from ..models import Part, Revision


def main_file_candidates(project):
    return Part.objects.filter(
        project=project, is_archived=False,
        revisions__file_format=Revision.FileFormat.FCSTD,
    ).distinct().order_by("number")


def latest_fcstd_revision(part):
    if part is None:
        return None
    all_revisions = getattr(part, "project_revisions", None)
    if all_revisions is not None:
        return next((revision for revision in all_revisions if revision.file_format == Revision.FileFormat.FCSTD), None)
    prefetched = getattr(part, "fcstd_revisions", None)
    if prefetched is not None:
        return prefetched[0] if prefetched else None
    return part.revisions.filter(file_format=Revision.FileFormat.FCSTD).order_by("-revision_code", "-pk").first()


def resolve_main_part(project, part_id):
    if part_id is None:
        return None
    if type(part_id) is not int or part_id < 1:
        raise ValidationError("Ungültige Hauptdatei.")
    part = main_file_candidates(project).filter(pk=part_id).first()
    if part is None:
        raise ValidationError("Die Hauptdatei muss eine aktive FCStd-Datei dieses Projekts sein.")
    return part
