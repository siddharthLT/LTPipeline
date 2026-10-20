import datetime

from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from .models import Account, MeetingNote, SentEmail, Task, TimelineEvent, normalize_domain
from .stages import STAGE_WEIGHTS


class Base(TestCase):
    def setUp(self):
        User.objects.create_user('a@b.co', 'pw-12345-xyz')
        self.client.login(username='a@b.co', password='pw-12345-xyz')
        self.account = Account.objects.create(name='OneSource', domain='onesource.com')


class DashboardTests(Base):
    def setUp(self):
        super().setUp()
        self.url = reverse('pipeline:dashboard')
        self.account.delete()

    def test_empty_state(self):
        self.assertContains(self.client.get(self.url), 'No Accounts Yet in Pipeline')

    def test_add_account_normalizes_domain_and_opens_thesis(self):
        r = self.client.post(self.url, {'name': ' Acme ', 'domain': 'https://www.Acme.com/about'})
        a = Account.objects.get()
        self.assertRedirects(r, reverse('pipeline:account_detail', args=[a.pk]))
        self.assertEqual((a.name, a.domain, a.score), ('Acme', 'acme.com', 0))
        self.assertEqual(a.stage_progress.count(), 12)
        self.assertNotContains(self.client.get(self.url), 'No Accounts Yet')

    def test_invalid_and_duplicate_domain(self):
        r = self.client.post(self.url, {'name': 'X', 'domain': 'not a domain'})
        self.assertContains(r, 'Enter a valid domain')
        Account.objects.create(name='A', domain='acme.com')
        r = self.client.post(self.url, {'name': 'B', 'domain': 'www.acme.com'})
        self.assertContains(r, 'already in the pipeline')

    def test_normalize(self):
        self.assertEqual(normalize_domain('HTTP://Foo.io/x?y=1'), 'foo.io')

    def test_gantt_shows_done_steps(self):
        a = Account.objects.create(name='N', domain='n.io')
        a.stage_progress.filter(stage__in=[1, 2, 3, 8]).update(done=True)
        cells = a.gantt_cells()
        states = [c['state'] for c in cells]
        self.assertEqual(states[:3], ['done', 'done', 'done'])
        self.assertEqual(states[7], 'now')
        self.assertIsNone(states[3])


class ScoreTests(Base):
    def test_weights_total_100(self):
        self.assertEqual(sum(STAGE_WEIGHTS.values()), 100)

    def test_onesource_example_is_25(self):
        self.account.stage_progress.filter(stage__in=[1, 2, 3, 8]).update(done=True)
        acct = Account.objects.get(pk=self.account.pk)
        self.assertEqual(acct.score, 25)
        self.assertEqual(acct.furthest_stage_name, 'Demo')

    def test_all_done_is_100(self):
        self.account.stage_progress.update(done=True)
        self.assertEqual(Account.objects.get(pk=self.account.pk).score, 100)


class ThesisTests(Base):
    def post(self, url, data):
        return self.client.post(url, data)

    def test_detail_renders(self):
        r = self.client.get(reverse('pipeline:account_detail', args=[self.account.pk]))
        self.assertContains(r, 'Buying thesis')
        self.assertContains(r, 'Tasks and next actions')

    def test_edit_company_overview_profile_icp(self):
        pk = self.account.pk
        for section, data in [
            ('company', {'name': 'OneSource Ltd', 'domain': 'onesource.com', 'deal_value': '$15K'}),
            ('overview', {'what_they_do': 'CDMO', 'what_they_service': 'Outsourcing', 'who_they_service': 'Biotechs'}),
            ('profile', {'modality': 'Biologics', 'therapeutic_focus': '', 'trial_phase': 'Ph2', 'geography': 'NA'}),
            ('icp', {'icp': 'Biotechs\nPharma', 'icp_source': 'Sep 21 call'}),
        ]:
            r = self.post(reverse('pipeline:edit_section', args=[pk, section]), data)
            self.assertEqual(r.status_code, 200, section)
        a = Account.objects.get(pk=pk)
        self.assertEqual((a.name, a.deal_value, a.modality, a.icp_source), ('OneSource Ltd', '$15K', 'Biologics', 'Sep 21 call'))
        r = self.client.get(reverse('pipeline:account_detail', args=[pk]))
        self.assertContains(r, '<li>Pharma</li>')

    def test_company_domain_can_keep_own_domain_but_not_clash(self):
        Account.objects.create(name='Other', domain='other.io')
        url = reverse('pipeline:edit_section', args=[self.account.pk, 'company'])
        self.assertEqual(self.post(url, {'name': 'X', 'domain': 'onesource.com'}).status_code, 200)
        self.assertEqual(self.post(url, {'name': 'X', 'domain': 'other.io'}).status_code, 400)

    def test_edit_stages_updates_score(self):
        data = {}
        for n in (1, 2, 3, 8):
            data[f'done_{n}'] = 'on'
            data[f'why_{n}'] = f'evidence {n}'
        r = self.post(reverse('pipeline:edit_section', args=[self.account.pk, 'stages']), data)
        self.assertEqual(r.status_code, 200)
        a = Account.objects.get(pk=self.account.pk)
        self.assertEqual(a.score, 25)
        self.assertEqual(a.stage_progress.get(stage=8).why, 'evidence 8')
        self.assertContains(self.client.get(reverse('pipeline:account_detail', args=[a.pk])), '25% score')

    def test_tasks_crud_and_toggle(self):
        pk = self.account.pk
        r = self.post(reverse('pipeline:item_new', args=[pk, 'task']),
                      {'kind': 'next_action', 'title': 'Send pricing', 'due_date': '2026-10-25'})
        self.assertEqual(r.status_code, 200)
        t = Task.objects.get()
        self.assertEqual(t.due_date, datetime.date(2026, 10, 25))
        bad = self.post(reverse('pipeline:item_new', args=[pk, 'task']), {'kind': 'task', 'title': 'No date'})
        self.assertEqual(bad.status_code, 400)
        self.post(reverse('pipeline:task_toggle', args=[pk, t.pk]), {})
        t.refresh_from_db()
        self.assertTrue(t.done)
        self.post(reverse('pipeline:item_delete', args=[pk, 'task', t.pk]), {})
        self.assertEqual(Task.objects.count(), 0)

    def test_meeting_parts_events_emails(self):
        pk = self.account.pk
        self.post(reverse('pipeline:item_new', args=[pk, 'meeting']), {'title': 'Sep 21 call', 'held_on': '2026-09-21'})
        m = MeetingNote.objects.get()
        r = self.post(reverse('pipeline:meeting_part', args=[pk, m.pk, 'who']), {'who': 'Jyoti\nSuneel'})
        self.assertEqual(r.status_code, 200)
        m.refresh_from_db()
        self.assertEqual(m.who, 'Jyoti\nSuneel')
        self.assertEqual(self.post(reverse('pipeline:meeting_part', args=[pk, m.pk, 'nope']), {}).status_code, 404)
        self.post(reverse('pipeline:item_new', args=[pk, 'event']), {'date': '2026-09-21', 'kind': 'call', 'text': 'Walkthrough'})
        self.post(reverse('pipeline:item_new', args=[pk, 'email']),
                  {'sent_on': '2026-09-29', 'subject': 'Recap', 'recipients': 'To: Jyoti', 'body': 'Hi team'})
        self.assertEqual((TimelineEvent.objects.count(), SentEmail.objects.count()), (1, 1))
        r = self.client.get(reverse('pipeline:account_detail', args=[pk]))
        for text in ('Sep 21 call', 'Walkthrough', 'Recap', 'Jyoti'):
            self.assertContains(r, text)

    def test_cannot_touch_other_accounts_items(self):
        other = Account.objects.create(name='O', domain='o.io')
        t = Task.objects.create(account=other, title='t', due_date=datetime.date(2026, 1, 1))
        r = self.client.post(reverse('pipeline:task_toggle', args=[self.account.pk, t.pk]))
        self.assertEqual(r.status_code, 404)

    def test_login_required(self):
        self.client.logout()
        r = self.client.get(reverse('pipeline:account_detail', args=[self.account.pk]))
        self.assertEqual(r.status_code, 302)
