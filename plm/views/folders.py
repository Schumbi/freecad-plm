from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.db.models.deletion import ProtectedError

from ..models import Project, ProjectFolder
from ..permissions import is_plm_admin


@login_required
def manage_project_folders(request):
    if not is_plm_admin(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Verwalten von Ordnern.")
    error = ""
    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            with transaction.atomic():
                folders = {f.pk: f for f in ProjectFolder.objects.select_for_update()}
                if action == "move_project":
                    project = get_object_or_404(Project, pk=request.POST.get("project_id"))
                    target = request.POST.get("parent_id") or None
                    if target is not None and (not target.isdecimal() or int(target) not in folders):
                        raise ValidationError("Ordner nicht gefunden.")
                    project.folder_id = int(target) if target else None
                    project.save(update_fields=["folder", "updated_at"])
                else:
                    folder_id = request.POST.get("folder_id")
                    folder = get_object_or_404(ProjectFolder, pk=folder_id) if folder_id else ProjectFolder()
                    if action == "delete":
                        folder.delete()
                    elif action in {"create", "update"}:
                        name = " ".join(request.POST.get("name", "").split())
                        if not name or len(name) > 200:
                            raise ValidationError("Bitte einen Ordnernamen mit höchstens 200 Zeichen angeben.")
                        target = request.POST.get("parent_id") or None
                        if target is not None and (not target.isdecimal() or int(target) not in folders):
                            raise ValidationError("Übergeordneter Ordner nicht gefunden.")
                        ancestor = int(target) if target else None
                        seen = set()
                        while ancestor is not None:
                            if ancestor == folder.pk or ancestor in seen:
                                raise ValidationError("Zyklische Ordnerstruktur ist nicht erlaubt.")
                            seen.add(ancestor)
                            ancestor = folders[ancestor].parent_id
                        folder.name, folder.parent_id = name, int(target) if target else None
                        folder.save()
                    else:
                        raise ValidationError("Unbekannte Aktion.")
            messages.success(request, "Projektordner aktualisiert.")
            return redirect("plm:manage_project_folders")
        except (ValidationError, IntegrityError, ProtectedError) as exc:
            error = "Nur leere Ordner können gelöscht werden." if isinstance(exc, ProtectedError) else " ".join(getattr(exc, "messages", [str(exc)]))
    folders = list(ProjectFolder.objects.select_related("parent").order_by("name"))
    by_id = {folder.pk: folder for folder in folders}
    def display_path(folder):
        names, seen = [], set()
        while folder and folder.pk not in seen:
            seen.add(folder.pk)
            names.append(folder.name)
            folder = by_id.get(folder.parent_id)
        return " / ".join(reversed(names))
    for folder in folders:
        folder.display_path = display_path(folder)
    return render(request, "plm/project_folders.html", {
        "folders": folders,
        "projects": Project.objects.select_related("folder").order_by("code"),
        "error": error,
    }, status=400 if error else 200)
