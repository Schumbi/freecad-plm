from functools import wraps
from hashlib import sha256
import secrets

from django.http import JsonResponse
from django.utils import timezone

from .models import ApiToken


TOKEN_PREFIX = "plm_pat_"
TOKEN_VISIBLE_PREFIX_LENGTH = 20
HTTP_METHOD_SCOPES = {
    "GET": ApiToken.Scope.READ,
    "HEAD": ApiToken.Scope.READ,
    "OPTIONS": ApiToken.Scope.READ,
}


def hash_api_token(raw_token):
    return sha256(raw_token.encode("utf-8")).hexdigest()


def generate_raw_api_token():
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def create_api_token(*, user, name, scopes=None, expires_at=None):
    raw_token = generate_raw_api_token()
    token = ApiToken.objects.create(
        user=user,
        name=name.strip(),
        token_prefix=raw_token[:TOKEN_VISIBLE_PREFIX_LENGTH],
        token_hash=hash_api_token(raw_token),
        scopes=list(scopes or [ApiToken.Scope.READ]),
        expires_at=expires_at,
    )
    return token, raw_token


def bearer_token_from_request(request):
    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return ""
    return value.strip()


def authenticate_api_token(request):
    raw_token = bearer_token_from_request(request)
    if not raw_token:
        return None
    token_hash = hash_api_token(raw_token)
    token = (
        ApiToken.objects.select_related("user")
        .filter(token_hash=token_hash)
        .first()
    )
    if token is None or not token.is_active():
        return None
    token.last_used_at = timezone.now()
    token.save(update_fields=["last_used_at", "updated_at"])
    return token


def token_has_scope(token, required_scope):
    if required_scope is None:
        return True
    scopes = set(token.scopes or [])
    return required_scope in scopes or ApiToken.Scope.ADMIN in scopes


def api_auth_required(**method_scopes):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            token = authenticate_api_token(request)
            if token is None:
                request.api_token = None
                return JsonResponse(
                    {"error": "API-Token erforderlich."},
                    status=401,
                )

            required_scope = method_scopes.get(
                request.method.lower(),
                HTTP_METHOD_SCOPES.get(request.method),
            )
            if not token_has_scope(token, required_scope):
                return JsonResponse(
                    {"error": "API-Token hat nicht den benoetigten Scope."},
                    status=403,
                )
            request.user = token.user
            request.api_token = token
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
