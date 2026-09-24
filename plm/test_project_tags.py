import json
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import QueryDict
from django.test import TestCase, Client
from django.urls import reverse
from .auth import create_api_token
from .forms import ProjectForm
from .models import Project, ProjectTag, ApiToken, AuditEvent
from .services.project_tags import set_project_tags, rename_or_merge_tag, filter_projects
from .services.search import search_plm


class ProjectTagTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username='tag-admin', password='test')
        self.reader = get_user_model().objects.create_user(username='tag-reader', password='test')
        self.client.force_login(self.admin)
        self.a = Project.objects.create(code='A', name='Halter')
        self.b = Project.objects.create(code='B', name='Box')
        self.c = Project.objects.create(code='C', name='Ohne')
        set_project_tags(self.a, ['Modellbau', 'Zubehör'])
        set_project_tags(self.b, ['Modellbau'])
        self.model = ProjectTag.objects.get(name='Modellbau')
        self.accessory = ProjectTag.objects.get(name='Zubehör')
        _, token = create_api_token(user=self.admin, name='tests', scopes=[ApiToken.Scope.ADMIN])
        self.auth = {'HTTP_AUTHORIZATION': 'Bearer ' + token}

    def test_normalization_and_assignment_reuses_tags(self):
        set_project_tags(self.b, [' modellbau ', 'MODELLBAU', '  Neue   Sachen '])
        self.assertEqual(ProjectTag.objects.count(), 3)
        self.assertEqual(self.b.tags.count(), 2)
        self.assertTrue(self.b.tags.filter(name='Neue Sachen').exists())

    def test_invalid_names_do_not_change_existing_assignments(self):
        for names in ([None], ['x'*81], ['bad,name'], {'name': 'X'}, ['x'+str(i) for i in range(101)]):
            with self.subTest(names=names), self.assertRaises(ValidationError):
                set_project_tags(self.b, names)
            self.assertEqual(list(self.b.tags.all()), [self.model])

    def test_all_any_text_and_untagged_filters(self):
        q = f'tag={self.model.pk}&tag={self.accessory.pk}'
        cases = [(q, ['A']), (q+'&mode=any', ['A', 'B']),
                 (q+'&mode=any&q=Box', ['B']), ('untagged=1', ['C']),
                 ('q=Modellbau', ['A', 'B']), ('tag=invalid', []),
                 ('tag=999999999999999999999999999999', []), (q+'&untagged=1', ['C'])]
        for query, expected in cases:
            with self.subTest(query=query):
                self.assertEqual(list(filter_projects(Project.objects.all(), QueryDict(query)).values_list('code', flat=True)), expected)

    def test_web_sidebar_filter_and_api_return_same_projects(self):
        query = {'tag': [self.accessory.pk]}
        response = self.client.get(reverse('plm:project_list'), query)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['projects']), [self.a])
        self.assertContains(response, 'Tags verwalten')
        response = self.client.get('/api/projects/', query, **self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p['id'] for p in response.json()['projects']], [self.a.id])
        self.assertEqual(len(response.json()['projects'][0]['tags']), 2)

    def test_global_search_finds_project_by_tag_without_duplicates(self):
        set_project_tags(self.b, ['Modellbau', 'Modellbau klein'])
        self.assertEqual([p.code for p in search_plm('Modellbau').projects], ['A', 'B'])

    def test_merge_preserves_all_project_links_including_archived(self):
        self.b.is_archived = True
        self.b.save()
        merged = rename_or_merge_tag(self.model, 'zubehör')
        self.assertEqual(merged.pk, self.accessory.pk)
        self.assertFalse(ProjectTag.objects.filter(pk=self.model.pk).exists())
        self.assertEqual(set(merged.projects.values_list('code', flat=True)), {'A', 'B'})
        self.assertEqual(self.a.tags.count(), 1)

    def test_case_only_rename_preserves_identity(self):
        updated = rename_or_merge_tag(self.model, 'MODELLBAU')
        self.assertEqual(updated.pk, self.model.pk)
        self.assertEqual(updated.projects.count(), 2)

    def test_admin_delete_requires_confirmation_and_keeps_projects(self):
        url = reverse('plm:manage_project_tags')
        data = {'tag_id': self.model.pk, 'action': 'delete'}
        self.assertEqual(self.client.post(url, data).status_code, 400)
        self.assertTrue(ProjectTag.objects.filter(pk=self.model.pk).exists())
        self.assertEqual(self.client.post(url, {**data, 'confirm':'yes'}).status_code, 302)
        self.assertEqual(Project.objects.count(), 3)
        self.assertEqual(self.a.tags.count(), 1)
        self.assertTrue(AuditEvent.objects.filter(action='project_tag_updated').exists())

    def test_readers_cannot_manage_or_change_tags(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse('plm:manage_project_tags')).status_code, 403)
        self.assertEqual(self.client.post(reverse('plm:manage_project_tags'), {'tag_id':self.model.pk, 'action':'delete','confirm':'yes'}).status_code, 403)
        _, raw = create_api_token(user=self.reader, name='read', scopes=[ApiToken.Scope.READ])
        self.assertEqual(self.client.post(f'/api/projects/{self.a.pk}/', json.dumps({'tags':[]}), content_type='application/json', HTTP_AUTHORIZATION='Bearer '+raw).status_code, 403)
        self.assertEqual(self.a.tags.count(), 2)

    def test_api_legacy_update_preserves_tags_and_explicit_empty_clears(self):
        url = f'/api/projects/{self.a.pk}/'
        for payload, count in [({'name':'Neuer Name'}, 2), ({'tags':[]}, 0), ({'tags':['modellbau']},1)]:
            response = self.client.post(url, json.dumps(payload), content_type='application/json', **self.auth)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.a.tags.count(), count)

    def test_invalid_api_tags_do_not_partially_save_project(self):
        response = self.client.post(f'/api/projects/{self.a.pk}/', json.dumps({'name':'Changed','tags':[3]}), content_type='application/json', **self.auth)
        self.assertEqual(response.status_code, 400)
        self.a.refresh_from_db()
        self.assertEqual(self.a.name, 'Halter')
        self.assertEqual(self.a.tags.count(), 2)

    def test_project_form_creates_and_reuses_tags(self):
        data = {'code':'NEW','name':'New','status':'idea','project_date':'2026-09-24',
                'tags':[self.model.pk], 'new_tags':'modellbau, Haushalt'}
        form = ProjectForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        project = form.save()
        self.assertEqual(set(project.tags.values_list('name',flat=True)), {'Modellbau', 'Haushalt'})
        self.assertEqual(self.client.get(reverse('plm:edit_project', args=[project.pk])).status_code, 200)

    def test_tag_management_post_merge_and_xss_escaping(self):
        set_project_tags(self.c, ['<script>alert(1)</script>'])
        response = self.client.get(reverse('plm:project_list'))
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
        response = self.client.post(reverse('plm:manage_project_tags'), {'tag_id':self.model.pk,'action':'rename','name':'Zubehör'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.accessory.projects.count(),2)

    def test_tag_mutations_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        response = client.post(reverse('plm:manage_project_tags'), {'tag_id':self.model.pk,'action':'delete','confirm':'yes'})
        self.assertEqual(response.status_code,403)
