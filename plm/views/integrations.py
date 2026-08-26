from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from ..integrations.bambuddy import BambuddyClient, BambuddyError
from .common import admin_required_response


@login_required
@require_http_methods(["GET", "POST"])
def integration_settings(request):
    forbidden = admin_required_response(request)
    if forbidden:
        return forbidden

    connection_result = None
    connection_error = ""
    configured = bool(settings.BAMBUDDY_URL and settings.BAMBUDDY_API_KEY)
    if request.method == "POST":
        try:
            info = BambuddyClient.from_settings().test_connection()
            archive_count = (
                str(info.total_archives)
                if info.total_archives is not None
                else f"mindestens {info.returned_archives}"
            )
            connection_result = (
                "Verbindung erfolgreich. "
                f"Bambuddy meldet {archive_count} Archiv(e)."
            )
        except BambuddyError as exc:
            connection_error = str(exc)

    return render(
        request,
        "plm/integration_settings.html",
        {
            "bambuddy_url": settings.BAMBUDDY_URL,
            "bambuddy_api_key_configured": bool(settings.BAMBUDDY_API_KEY),
            "bambuddy_timeout_seconds": settings.BAMBUDDY_TIMEOUT_SECONDS,
            "bambuddy_configured": configured,
            "connection_result": connection_result,
            "connection_error": connection_error,
        },
        status=502 if connection_error else 200,
    )
