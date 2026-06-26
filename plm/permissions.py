ROLE_ADMIN = "admin"
ROLE_EDITOR = "editor"
ROLE_READER = "reader"

ROLE_NAMES = (ROLE_ADMIN, ROLE_EDITOR, ROLE_READER)


def is_plm_admin(user):
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name=ROLE_ADMIN).exists()
    )


def can_upload_revision(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=(ROLE_ADMIN, ROLE_EDITOR)).exists()


def can_release_revision(user):
    return is_plm_admin(user)


def can_edit_revision_notes(user):
    return can_upload_revision(user)
