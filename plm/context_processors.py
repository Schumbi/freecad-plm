"""Globale Template-Kontexte fuer die Anwendungsschale."""

ADMIN_URL_NAMES = {
    "user_management",
    "create_user",
    "edit_user",
    "set_user_password",
    "create_user_token",
    "edit_api_token",
    "revoke_api_token",
    "delete_api_token",
}

INTEGRATION_URL_NAMES = {"integration_settings"}

# Diese Seiten gehoeren zu keinem Arbeitsbereich.
NEUTRAL_URL_NAMES = {"login", "logout"}


def navigation(request):
    """Leitet den aktiven Arbeitsbereich aus der aufgeloesten URL ab.

    Die Views muessen dadurch kein ``active_section`` mehr einzeln setzen.
    """
    match = getattr(request, "resolver_match", None)
    if match is None or match.namespace != "plm":
        return {}

    url_name = match.url_name or ""
    if url_name in NEUTRAL_URL_NAMES or not url_name:
        section = ""
    elif url_name in ADMIN_URL_NAMES:
        section = "admin"
    elif url_name in INTEGRATION_URL_NAMES:
        section = "integrations"
    else:
        # Projekte, Teile, Revisionen, Suche und Fertigung sind Teil des
        # Projektarbeitsbereichs.
        section = "projects"

    return {"active_section": section}
