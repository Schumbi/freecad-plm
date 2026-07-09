from django import template

from plm.permissions import is_plm_admin


register = template.Library()


@register.filter
def can_manage_plm(user):
    return is_plm_admin(user)
