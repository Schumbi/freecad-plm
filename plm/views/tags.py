from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponseForbidden, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.db.models import Count
from django.db import transaction
from ..models import ProjectTag, AuditEvent
from ..permissions import is_plm_admin
from ..services.project_tags import rename_or_merge_tag


@login_required
@transaction.atomic
def manage_project_tags(request):
    if not is_plm_admin(request.user):
        return HttpResponseForbidden("Keine Berechtigung zum Verwalten von Tags.")
    error = ""
    if request.method == "POST":
        tag_id = request.POST.get("tag_id", "")
        if not tag_id.isdecimal() or len(tag_id) > 18:
            return HttpResponseBadRequest("Ungültiger Tag.")
        tag = get_object_or_404(ProjectTag, pk=tag_id)
        old_name = tag.name
        action = request.POST.get("action")
        try:
            if action == "delete":
                if request.POST.get("confirm") != "yes":
                    raise ValidationError("Bitte das Entfernen des Tags bestätigen.")
                tag.delete()
            elif action == "rename":
                tag = rename_or_merge_tag(tag, request.POST.get("name", ""))
            else:
                raise ValidationError("Unbekannte Aktion.")
            AuditEvent.objects.create(actor=request.user, action=AuditEvent.Action.PROJECT_TAG_UPDATED,
                object_repr=old_name, metadata={"operation": action,
                    "new_name": tag.name if action == "rename" else None})
            messages.success(request, "Tag-Verwaltung aktualisiert. Die Projekte bleiben erhalten.")
            return redirect("plm:manage_project_tags")
        except ValidationError as exc:
            error = " ".join(exc.messages)
    return render(request, "plm/project_tags.html", {
        "tags": ProjectTag.objects.annotate(project_count=Count("projects")), "error": error,
    }, status=400 if error else 200)
