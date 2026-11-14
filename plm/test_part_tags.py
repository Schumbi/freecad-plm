from hashlib import sha256

from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import PartTag


class PartTagModelTests(TestCase):
    def test_name_is_normalized_and_identity_is_case_insensitive(self):
        tag = PartTag.objects.create(name="  Äußeres \t &  Prüfung  ")
        self.assertEqual(tag.name, "Äußeres & Prüfung")
        self.assertEqual(
            tag.identity_hash,
            sha256("äusseres & prüfung".encode("utf-8")).hexdigest(),
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            PartTag.objects.create(name="ÄUSSERES & PRÜFUNG")

    def test_empty_and_comma_names_are_rejected(self):
        for name in (" \t ", "eins,zwei"):
            with self.subTest(name=name), self.assertRaisesMessage(
                Exception, "darf nicht leer sein oder ein Komma enthalten"
            ):
                PartTag.objects.create(name=name)
