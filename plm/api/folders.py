from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..auth import api_auth_required
from ..models import ApiToken, ProjectFolder
from ..permissions import is_plm_admin
from .common import json_body


def payload(folder):
    return {"id": folder.pk, "name": folder.name, "parent_id": folder.parent_id}


def save_folder(request, folder):
    if not is_plm_admin(request.user):
        return JsonResponse({"error": "Keine Berechtigung."}, status=403)
    data = json_body(request)
    name = data.get("name", folder.name)
    parent_id = data.get("parent_id", folder.parent_id)
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 200:
        return JsonResponse({"error": "Ungültiger Ordnername."}, status=400)
    if parent_id is not None and (not isinstance(parent_id, int) or isinstance(parent_id, bool)):
        return JsonResponse({"error": "Ungültiger übergeordneter Ordner."}, status=400)
    try:
        with transaction.atomic():
            # Serialize hierarchy edits on databases supporting row locks.
            folders = {item.pk: item for item in ProjectFolder.objects.select_for_update().order_by("pk")}
            if parent_id is not None and parent_id not in folders:
                return JsonResponse({"error": "Ordner nicht gefunden."}, status=400)
            ancestor = parent_id
            seen = set()
            while ancestor is not None:
                if ancestor == folder.pk or ancestor in seen:
                    return JsonResponse({"error": "Zyklische Ordnerstruktur ist nicht erlaubt."}, status=400)
                seen.add(ancestor)
                ancestor = folders[ancestor].parent_id
            folder.name, folder.parent_id = name.strip(), parent_id
            folder.save()
    except IntegrityError:
        return JsonResponse({"error": "Dieser Ordnername ist bereits vergeben."}, status=400)
    return JsonResponse({"folder": payload(folder)}, status=201 if request.method == "POST" and request.path.endswith("folders/") else 200)


@csrf_exempt
@api_auth_required(get=ApiToken.Scope.READ, post=ApiToken.Scope.ADMIN)
@require_http_methods(["GET", "POST"])
def folders_api(request):
    if request.method == "GET":
        return JsonResponse({"folders": [payload(folder) for folder in ProjectFolder.objects.all()]})
    return save_folder(request, ProjectFolder())


@csrf_exempt
@api_auth_required(post=ApiToken.Scope.ADMIN, delete=ApiToken.Scope.ADMIN)
@require_http_methods(["POST", "DELETE"])
def folder_api(request, folder_id):
    folder = get_object_or_404(ProjectFolder, pk=folder_id)
    if request.method == "POST":
        return save_folder(request, folder)
    if not is_plm_admin(request.user):
        return JsonResponse({"error": "Keine Berechtigung."}, status=403)
    from django.db.models.deletion import ProtectedError
    try:
        folder.delete()
    except ProtectedError:
        return JsonResponse({"error": "Nur leere Ordner können gelöscht werden."}, status=409)
    return JsonResponse({"deleted": True})
