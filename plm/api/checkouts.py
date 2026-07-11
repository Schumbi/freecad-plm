import json

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from ..auth import api_auth_required
from ..models import ApiToken, Checkout, ProjectSnapshot, Revision
from ..permissions import is_plm_admin
from ..services import cancel_checkout, checkin_checkout, checkin_checkout_files, checkout_manifest, create_checkout

from .common import (
    active_checkout_payload,
    add_manifest_download_urls,
    checkout_payload,
    json_body,
    revision_payload,
    revision_summary_payload,
    user_can_mutate_models,
    validation_error_response,
)


@csrf_exempt
@api_auth_required(post=ApiToken.Scope.CHECKOUT)
@require_http_methods(["POST"])
def revision_checkout_api(request, revision_id):
    if not user_can_mutate_models(request.user):
        return JsonResponse({"error": "Keine Berechtigung zum Auschecken."}, status=403)
    revision = get_object_or_404(
        Revision.objects.select_related("part", "part__project"),
        id=revision_id,
    )
    data = json_body(request)
    snapshot = None
    if data.get("snapshot_id"):
        snapshot = get_object_or_404(
            ProjectSnapshot,
            id=data["snapshot_id"],
            project=revision.part.project,
        )
    try:
        checkout = create_checkout(
            base_revision=revision,
            checked_out_by=request.user,
            snapshot=snapshot,
            workspace_hint=data.get("workspace_hint", ""),
        )
    except ValidationError as exc:
        return validation_error_response(exc, status=409)
    return JsonResponse(
        {
            "checkout": checkout_payload(checkout),
            "manifest": add_manifest_download_urls(checkout_manifest(checkout), request),
        },
        status=201,
    )


@api_auth_required(get=ApiToken.Scope.CHECKOUT)
@require_http_methods(["GET"])
def active_checkouts_api(request):
    checkouts = (
        Checkout.objects.select_related(
            "part",
            "part__project",
            "base_revision",
            "snapshot",
        )
        .filter(
            checked_out_by=request.user,
            status=Checkout.Status.ACTIVE,
        )
        .order_by("-updated_at", "-created_at")
    )
    return JsonResponse(
        {"checkouts": [active_checkout_payload(checkout) for checkout in checkouts]}
    )


@api_auth_required(get=ApiToken.Scope.READ)
@require_http_methods(["GET"])
def checkout_manifest_api(request, checkout_id):
    checkout = get_object_or_404(
        Checkout.objects.select_related(
            "part",
            "part__project",
            "base_revision",
            "snapshot",
            "checked_out_by",
        ),
        id=checkout_id,
    )
    manifest = checkout_manifest(checkout)
    add_manifest_download_urls(manifest, request)
    return JsonResponse({"checkout": checkout_payload(checkout), "manifest": manifest})


@csrf_exempt
@api_auth_required(post=ApiToken.Scope.CHECKOUT)
@require_http_methods(["POST"])
def checkout_cancel_api(request, checkout_id):
    checkout = get_object_or_404(Checkout, id=checkout_id)
    if checkout.checked_out_by_id != request.user.id and not is_plm_admin(request.user):
        return JsonResponse({"error": "Nur der Checkout-Besitzer darf abbrechen."}, status=403)
    try:
        cancel_checkout(checkout, request.user)
    except ValidationError as exc:
        return validation_error_response(exc, status=409)
    return JsonResponse({"checkout": checkout_payload(checkout)})


@csrf_exempt
@api_auth_required(post=ApiToken.Scope.CHECKOUT)
@require_http_methods(["POST"])
def checkout_checkin_api(request, checkout_id):
    checkout = get_object_or_404(Checkout.objects.select_related("part"), id=checkout_id)
    if checkout.checked_out_by_id != request.user.id and not is_plm_admin(request.user):
        return JsonResponse({"error": "Nur der Checkout-Besitzer darf einchecken."}, status=403)
    files_metadata = request.POST.get("files_metadata")
    if files_metadata is not None:
        try:
            parsed_metadata = json.loads(files_metadata)
        except json.JSONDecodeError:
            return JsonResponse({"error": "files_metadata muss gueltiges JSON sein."}, status=400)
        if not isinstance(parsed_metadata, list):
            return JsonResponse({"error": "files_metadata muss eine Liste sein."}, status=400)
        try:
            result = checkin_checkout_files(
                checkout,
                parsed_metadata,
                request.FILES,
                request.user,
                notes=request.POST.get("change_summary", ""),
            )
        except ValidationError as exc:
            return validation_error_response(exc, status=409)
        checkout.refresh_from_db()
        root_revision = result["root_revision"]
        return JsonResponse(
            {
                "checkout": checkout_payload(checkout),
                "revision": (
                    revision_summary_payload(root_revision) if root_revision else None
                ),
                "revisions": [
                    {
                        "path": item["path"],
                        "revision": revision_summary_payload(item["revision"]),
                    }
                    for item in result["revisions"]
                ],
                "ignored_files": result["ignored_files"],
            },
            status=201 if result["revisions"] else 200,
        )

    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        return JsonResponse({"error": "FCStd-Datei fehlt."}, status=400)
    try:
        result = checkin_checkout(
            checkout,
            uploaded_file,
            request.user,
            notes=request.POST.get("change_summary", ""),
        )
    except ValidationError as exc:
        return validation_error_response(exc, status=409)
    checkout.refresh_from_db()
    revision = result["root_revision"]
    return JsonResponse(
        {
            "checkout": checkout_payload(checkout),
            "revision": revision_payload(revision, request) if revision else None,
            "revisions": [
                {
                    "path": item["path"],
                    "revision": revision_summary_payload(item["revision"]),
                }
                for item in result["revisions"]
            ],
            "ignored_files": result["ignored_files"],
        },
        status=201 if result["revisions"] else 200,
    )
