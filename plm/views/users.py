from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from ..auth import create_api_token
from ..forms import AdminSetPasswordForm, ApiTokenForm, UserManagementForm, set_user_role, token_preset_for_scopes, token_preset_label, user_role
from ..models import ApiToken, AuditEvent

from .common import (
    admin_required_response,
    token_status,
    validate_user_admin_safety,
)


@login_required
@require_POST
def logout_view(request):
    logout(request)
    return redirect("plm:login")


@login_required
def user_management_list(request):
    forbidden = admin_required_response(request)
    if forbidden:
        return forbidden

    users = list(
        get_user_model()
        .objects.prefetch_related("groups", "api_tokens")
        .order_by("username")
    )
    tokens = list(
        ApiToken.objects.select_related("user")
        .order_by("user__username", "name")
    )
    user_rows = [
        {
            "user": user,
            "role": user_role(user) or "-",
            "token_count": user.api_tokens.count(),
        }
        for user in users
    ]
    token_rows = [
        {
            "token": token,
            "preset": token_preset_label(token_preset_for_scopes(token.scopes)),
            "status": token_status(token),
        }
        for token in tokens
    ]
    return render(
        request,
        "plm/user_management.html",
        {
            "user_rows": user_rows,
            "token_rows": token_rows,
        },
    )


@login_required
def create_user(request):
    forbidden = admin_required_response(request)
    if forbidden:
        return forbidden

    if request.method == "POST":
        form = UserManagementForm(request.POST, is_create=True)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password"])
            user.save()
            set_user_role(user, form.cleaned_data["role"])
            AuditEvent.objects.create(
                actor=request.user,
                action=AuditEvent.Action.USER_CREATED,
                object_repr=user.get_username(),
                metadata={"user_id": user.id, "role": form.cleaned_data["role"]},
            )
            messages.success(request, f"Benutzer {user.username} wurde angelegt.")
            return redirect("plm:user_management")
    else:
        form = UserManagementForm(is_create=True)

    return render(
        request,
        "plm/user_form.html",
        {
            "form": form,
            "title": "Benutzer anlegen",
            "submit_label": "Anlegen",
        },
        status=400 if request.method == "POST" else 200,
    )


@login_required
def edit_user(request, user_id):
    forbidden = admin_required_response(request)
    if forbidden:
        return forbidden

    target_user = get_object_or_404(get_user_model(), id=user_id)
    if request.method == "POST":
        form = UserManagementForm(request.POST, instance=target_user)
        if form.is_valid():
            safety_error = validate_user_admin_safety(
                target_user,
                request.user,
                form.cleaned_data["role"],
                form.cleaned_data["is_active"],
            )
            if safety_error:
                form.add_error(None, safety_error)
            else:
                user = form.save()
                set_user_role(user, form.cleaned_data["role"])
                AuditEvent.objects.create(
                    actor=request.user,
                    action=AuditEvent.Action.USER_UPDATED,
                    object_repr=user.get_username(),
                    metadata={
                        "user_id": user.id,
                        "role": form.cleaned_data["role"],
                        "is_active": user.is_active,
                    },
                )
                messages.success(request, f"Benutzer {user.username} wurde gespeichert.")
                return redirect("plm:user_management")
    else:
        form = UserManagementForm(instance=target_user)

    return render(
        request,
        "plm/user_form.html",
        {
            "form": form,
            "managed_user": target_user,
            "title": f"Benutzer bearbeiten: {target_user.username}",
            "submit_label": "Speichern",
        },
        status=400 if request.method == "POST" else 200,
    )


@login_required
def set_user_password(request, user_id):
    forbidden = admin_required_response(request)
    if forbidden:
        return forbidden

    target_user = get_object_or_404(get_user_model(), id=user_id)
    if request.method == "POST":
        form = AdminSetPasswordForm(target_user, request.POST)
        if form.is_valid():
            form.save()
            AuditEvent.objects.create(
                actor=request.user,
                action=AuditEvent.Action.USER_PASSWORD_SET,
                object_repr=target_user.get_username(),
                metadata={"user_id": target_user.id},
            )
            messages.success(
                request,
                f"Passwort fuer {target_user.username} wurde gesetzt.",
            )
            return redirect("plm:user_management")
    else:
        form = AdminSetPasswordForm(target_user)

    return render(
        request,
        "plm/user_password_form.html",
        {
            "form": form,
            "managed_user": target_user,
        },
        status=400 if request.method == "POST" else 200,
    )


@login_required
def create_user_token(request, user_id):
    forbidden = admin_required_response(request)
    if forbidden:
        return forbidden

    target_user = get_object_or_404(get_user_model(), id=user_id)
    raw_token = ""
    token = None
    if request.method == "POST":
        form = ApiTokenForm(request.POST, token_user=target_user)
        if form.is_valid():
            token, raw_token = create_api_token(
                user=target_user,
                name=form.cleaned_data["name"],
                scopes=form.scopes,
                expires_at=form.cleaned_data["expires_at"],
            )
            AuditEvent.objects.create(
                actor=request.user,
                action=AuditEvent.Action.API_TOKEN_CREATED,
                object_repr=str(token),
                metadata={
                    "user_id": target_user.id,
                    "token_id": token.id,
                    "scopes": token.scopes,
                },
            )
            messages.success(
                request,
                "API-Token wurde angelegt. Der Token wird nur jetzt angezeigt.",
            )
    else:
        form = ApiTokenForm(token_user=target_user)

    return render(
        request,
        "plm/api_token_form.html",
        {
            "form": form,
            "managed_user": target_user,
            "token": token,
            "raw_token": raw_token,
            "title": f"API-Token fuer {target_user.username} anlegen",
            "submit_label": "Token anlegen",
        },
        status=201 if raw_token else (400 if request.method == "POST" else 200),
    )


@login_required
def edit_api_token(request, token_id):
    forbidden = admin_required_response(request)
    if forbidden:
        return forbidden

    token = get_object_or_404(ApiToken.objects.select_related("user"), id=token_id)
    if request.method == "POST":
        form = ApiTokenForm(request.POST, instance=token, token_user=token.user)
        if form.is_valid():
            token = form.save(commit=False)
            token.scopes = form.scopes
            token.save(update_fields=["name", "scopes", "expires_at", "updated_at"])
            AuditEvent.objects.create(
                actor=request.user,
                action=AuditEvent.Action.API_TOKEN_UPDATED,
                object_repr=str(token),
                metadata={
                    "user_id": token.user_id,
                    "token_id": token.id,
                    "scopes": token.scopes,
                },
            )
            messages.success(request, f"API-Token {token.name} wurde gespeichert.")
            return redirect("plm:user_management")
    else:
        form = ApiTokenForm(instance=token, token_user=token.user)

    return render(
        request,
        "plm/api_token_form.html",
        {
            "form": form,
            "managed_user": token.user,
            "token": token,
            "title": f"API-Token bearbeiten: {token.name}",
            "submit_label": "Speichern",
        },
        status=400 if request.method == "POST" else 200,
    )


@login_required
def revoke_api_token(request, token_id):
    forbidden = admin_required_response(request)
    if forbidden:
        return forbidden
    if request.method != "POST":
        return redirect("plm:user_management")

    token = get_object_or_404(ApiToken.objects.select_related("user"), id=token_id)
    if not token.is_revoked:
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at", "updated_at"])
        AuditEvent.objects.create(
            actor=request.user,
            action=AuditEvent.Action.API_TOKEN_REVOKED,
            object_repr=str(token),
            metadata={"user_id": token.user_id, "token_id": token.id},
        )
        messages.success(request, f"API-Token {token.name} wurde widerrufen.")
    return redirect("plm:user_management")
