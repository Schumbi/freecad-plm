"""Shared project tagging and filtering for the web and API."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from ..models import ProjectTag


def tag_names(value):
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ValidationError("Tags müssen als Liste von Namen angegeben werden.")
    names = {}
    for raw in value:
        name = " ".join(raw.split())
        if not name:
            continue
        if len(name) > 80 or "," in name:
            raise ValidationError("Ein Tag darf höchstens 80 Zeichen und kein Komma enthalten.")
        names.setdefault(name.casefold(), name)
    if len(names) > 100:
        raise ValidationError("Höchstens 100 Tags pro Projekt sind erlaubt.")
    return list(names.values())


@transaction.atomic
def set_project_tags(project, names):
    tags = [ProjectTag.objects.get_or_create(key=n.casefold(), defaults={"name": n})[0]
            for n in tag_names(names)]
    project.tags.set(tags)


def filter_projects(projects, params):
    query = params.get("q", "").strip()
    if query:
        projects = projects.filter(Q(code__icontains=query) | Q(name__icontains=query)
            | Q(description__icontains=query) | Q(tags__name__icontains=query))
    selected = params.getlist("tag")
    if params.get("untagged") == "1":
        projects = projects.filter(tags__isnull=True)
    elif selected:
        if any((not value.isdecimal() or len(value) > 18) for value in selected):
            return projects.none()
        if params.get("mode") == "any":
            projects = projects.filter(tags__id__in=selected)
        else:
            for tag_id in set(selected):
                projects = projects.filter(tags__id=tag_id)
    return projects.distinct()


@transaction.atomic
def rename_or_merge_tag(tag, name):
    names = tag_names([name])
    if len(names) != 1:
        raise ValidationError("Bitte einen Namen angeben.")
    name = names[0]
    # Lock both tags consistently before moving the associations.
    locked = list(ProjectTag.objects.select_for_update().filter(
        Q(pk=tag.pk) | Q(key=name.casefold())).order_by("pk"))
    tag = next(t for t in locked if t.pk == tag.pk)
    target = next((t for t in locked if t.key == name.casefold() and t.pk != tag.pk), None)
    if target:
        through = tag.projects.through
        through.objects.bulk_create([
            through(project_id=pid, projecttag_id=target.pk)
            for pid in tag.projects.values_list("pk", flat=True)
        ], ignore_conflicts=True)
        tag.delete()
        return target
    tag.name = name
    tag.save()
    return tag
