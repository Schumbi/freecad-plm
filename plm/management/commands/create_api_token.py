from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from plm.auth import create_api_token
from plm.models import ApiToken


class Command(BaseCommand):
    help = "Create a PLM API token for a Django user."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("name")
        parser.add_argument(
            "--scope",
            action="append",
            dest="scopes",
            choices=[choice.value for choice in ApiToken.Scope],
            help="Token scope. Can be passed multiple times.",
        )
        parser.add_argument(
            "--expires-at",
            help="Optional ISO datetime, for example 2026-12-31T23:59:00+01:00.",
        )

    def handle(self, *args, **options):
        username = options["username"]
        try:
            user = get_user_model().objects.get(username=username)
        except get_user_model().DoesNotExist as exc:
            raise CommandError(f"User does not exist: {username}") from exc

        expires_at = None
        if options.get("expires_at"):
            expires_at = parse_datetime(options["expires_at"])
            if expires_at is None:
                raise CommandError("--expires-at must be an ISO datetime.")
            if timezone.is_naive(expires_at):
                expires_at = timezone.make_aware(expires_at)

        token, raw_token = create_api_token(
            user=user,
            name=options["name"],
            scopes=options.get("scopes") or [ApiToken.Scope.READ],
            expires_at=expires_at,
        )
        self.stdout.write(self.style.SUCCESS("API token created."))
        self.stdout.write(f"User: {user.username}")
        self.stdout.write(f"Name: {token.name}")
        self.stdout.write(f"Scopes: {', '.join(token.scopes)}")
        self.stdout.write(f"Prefix: {token.token_prefix}")
        self.stdout.write("")
        self.stdout.write("Token:")
        self.stdout.write(raw_token)
