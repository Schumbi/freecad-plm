from django.core.management.base import BaseCommand

from plm.freecadcmd import process_queued_export_jobs


class Command(BaseCommand):
    help = "Verarbeitet wartende FreeCADCmd-Exportjobs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximale Anzahl Jobs fuer diesen Lauf.",
        )

    def handle(self, *args, **options):
        jobs = process_queued_export_jobs(limit=options["limit"])
        succeeded = sum(1 for job in jobs if job.status == job.Status.SUCCEEDED)
        failed = sum(1 for job in jobs if job.status == job.Status.FAILED)
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(jobs)} Job(s) verarbeitet: {succeeded} erfolgreich, {failed} fehlgeschlagen."
            )
        )
