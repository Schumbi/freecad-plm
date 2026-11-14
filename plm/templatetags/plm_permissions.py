from django import template

from plm.permissions import is_plm_admin


register = template.Library()


@register.filter
def can_manage_plm(user):
    return is_plm_admin(user)


@register.filter
def has_required_fields(form):
    """True, wenn das Formular sichtbare Pflichtfelder enthaelt."""
    if form is None:
        return False
    for field in form:
        if field.field.required and not field.is_hidden:
            return True
    return False
