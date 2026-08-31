from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from plm.integrations.bambuddy import BambuddyError
from plm.services.bambuddy import sync_bambuddy_print_projects, sync_bambuddy_source_projects


class Command(BaseCommand):
    help = "Verknüpft Bambuddy-Druckarchive mit PLM-Revision und Source-3MF."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Maximale Anzahl der jüngsten Bambuddy-Archive.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Zuordnungen prüfen, ohne Bambuddy oder PLM-Metadaten zu ändern.",
        )

    def handle(self, *args, **options):
        if not settings.BAMBUDDY_SOURCE_SYNC_ENABLED and not options["dry_run"]:
            return
        try:
            result = sync_bambuddy_source_projects(
                limit=options["limit"],
                dry_run=options["dry_run"],
            )
            print_result = sync_bambuddy_print_projects(
                limit=options["limit"], dry_run=options["dry_run"]
            )
        except BambuddyError as exc:
            raise CommandError(str(exc)) from exc

        mode = "Dry-Run" if options["dry_run"] else "Sync"
        self.stdout.write(
            self.style.SUCCESS(
                f"Bambuddy-{mode}: {result.inspected} geprüft, "
                f"{result.matched} eindeutig zugeordnet, "
                f"{result.uploaded} hochgeladen, "
                f"{result.linked} verlinkt, "
                f"{result.unmatched} ohne PLM-Treffer, "
                f"{result.ambiguous} mehrdeutig."
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Druckprojekt-{mode}: {print_result.inspected} geprüft, "
                f"{print_result.matched} eindeutig zugeordnet, "
                f"{print_result.uploaded} hochgeladen."
            )
        )
