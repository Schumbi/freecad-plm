from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from plm.permissions import ROLE_ADMIN, ROLE_EDITOR, ROLE_NAMES, ROLE_READER


class Command(BaseCommand):
    help = "Create PLM role groups and assign initial model permissions."

    def handle(self, *args, **options):
        groups = {name: Group.objects.get_or_create(name=name)[0] for name in ROLE_NAMES}

        all_plm_permissions = Permission.objects.filter(content_type__app_label="plm")
        view_plm_permissions = all_plm_permissions.filter(codename__startswith="view_")
        change_plm_permissions = all_plm_permissions.exclude(codename__startswith="delete_")

        groups[ROLE_READER].permissions.set(view_plm_permissions)
        groups[ROLE_EDITOR].permissions.set(change_plm_permissions)
        groups[ROLE_ADMIN].permissions.set(all_plm_permissions)

        self.stdout.write(self.style.SUCCESS("PLM roles are ready."))
