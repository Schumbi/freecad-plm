"""Erzeugt fehlende oder veraltete 3D-Vorschauen im Hintergrund."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from plm.derivatives import revision_has_pending_png_job
from plm.freecadcmd import PREVIEW_GENERATOR_VERSION
from plm.models import Revision
from plm.views.common import ensure_revision_viewer_preview, revision_viewer_artifact


class Command(BaseCommand):
    help = (
        "Listet Revisionen ohne aktuelle 3D-Vorschau und legt mit --apply "
        "Hintergrundjobs zum Neuerzeugen an."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Jobs wirklich anlegen (ohne diese Option nur Vorschau).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Maximale Anzahl Revisionen (0 = alle).",
        )
        parser.add_argument(
            "--user",
            default="",
            help="Benutzername für die Job-Erstellung (Standard: erster Superuser).",
        )

    def handle(self, *args, **options):
        queryset = (
            Revision.objects.select_related("part", "part__project", "created_by")
            .exclude(file_format=Revision.FileFormat.STL)
            .order_by("id")
        )
        candidates = []
        for revision in queryset.iterator():
            if revision_viewer_artifact(revision):
                continue
            if revision_has_pending_png_job(revision):
                continue
            candidates.append(revision)

        limit = options["limit"]
        if limit:
            candidates = candidates[:limit]

        self.stdout.write(
            f"{len(candidates)} Revision(en) ohne Vorschau der Generation "
            f"{PREVIEW_GENERATOR_VERSION}."
        )
        for revision in candidates[:20]:
            self.stdout.write(
                f"  {revision.part.project.code} · {revision.part.number} "
                f"· {revision.revision_code} · {revision.original_filename}"
            )
        if len(candidates) > 20:
            self.stdout.write(f"  … und {len(candidates) - 20} weitere")

        if not options["apply"]:
            self.stdout.write("Nur Vorschau. Mit --apply werden Jobs angelegt.")
            return

        username = options["user"].strip()
        user = (
            get_user_model().objects.filter(username=username).first()
            if username
            else get_user_model().objects.filter(is_superuser=True).order_by("id").first()
        )
        if user is None:
            raise CommandError("Kein passender Benutzer gefunden (--user angeben).")

        created = 0
        for revision in candidates:
            status = ensure_revision_viewer_preview(
                revision, user, process_inline=False
            )
            if status == "queued":
                created += 1
        self.stdout.write(
            self.style.SUCCESS(f"{created} Vorschau-Job(s) eingeplant.")
        )
