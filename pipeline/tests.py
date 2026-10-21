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


class SnapshotTests(TestCase):
    def setUp(self):
        from accounts.models import User
        self.user = User.objects.create_user(email='t@lunartree.bio', password='x-pass-123')
        self.client.force_login(self.user)
        self.a = Account.objects.create(name='Acme', domain='acme.com')

    def tick(self, *nums):
        self.a.stage_progress.filter(stage__in=nums).update(done=True)

    def test_schedule_runs_open_steps_in_order_and_flags_gaps(self):
        import datetime as dt
        from .stages import STAGE_DAYS
        self.tick(1, 2, 3, 8)
        today = dt.date(2026, 10, 20)
        s = {r['num']: r for r in self.a.schedule(today)}
        self.assertTrue(s[1]['done'] and s[8]['done'])
        self.assertTrue(s[4]['gap'] and s[7]['gap'])
        self.assertEqual(s[4]['date'], today + dt.timedelta(days=STAGE_DAYS[4]))
        self.assertEqual(s[9]['date'], today + dt.timedelta(days=STAGE_DAYS[9]))
        self.assertEqual(s[10]['date'], s[9]['date'] + dt.timedelta(days=STAGE_DAYS[10]))
        self.assertEqual(self.a.next_stage['num'], 9)

    def test_target_date_overrides_and_moves_later_steps(self):
        import datetime as dt
        from .stages import STAGE_DAYS
        self.tick(1, 2, 3)
        self.a.stage_progress.filter(stage=5).update(target_date=dt.date(2027, 1, 10))
        s = {r['num']: r for r in self.a.schedule(dt.date(2026, 10, 20))}
        self.assertEqual(s[5]['date'], dt.date(2027, 1, 10))
        self.assertTrue(s[5]['override'])
        self.assertEqual(s[6]['date'], dt.date(2027, 1, 10) + dt.timedelta(days=STAGE_DAYS[6]))

    def test_path_updates_with_stages(self):
        self.assertEqual(self.a.path_pct, 0)
        self.tick(1, 2, 3, 4, 5, 6, 7, 8)
        p = self.a.path_steps()
        self.assertEqual(p[0]['state'], 'done')
        self.assertEqual(p[1]['state'], 'now')
        self.tick(10)
        p = self.a.path_steps()
        self.assertEqual(p[1]['state'], 'done')  # a done pilot implies the usage checks
        self.assertEqual(p[2]['pct'], 50)
        self.tick(11, 12)
        self.assertEqual(self.a.path_steps()[3]['state'], 'done')

    def test_usage_flags_drive_real_usage(self):
        self.a.usage_tried = True
        self.a.save()
        self.assertEqual(self.a.path_steps()[1]['pct'], 33)

    def test_pages_and_edit_forms_render_and_save(self):
        r = self.client.get(reverse('pipeline:dashboard'))
        self.assertContains(r, 'scorechip')
        r = self.client.get(reverse('pipeline:account_detail', args=[self.a.pk]))
        self.assertContains(r, 'Deal snapshot')
        self.assertContains(r, 'Buying thesis in short')
        for section in ['people', 'move', 'next', 'usage', 'why', 'first', 'before', 'expand', 'commercial', 'whynot', 'stages']:
            self.assertEqual(self.client.get(reverse('pipeline:edit_section', args=[self.a.pk, section])).status_code, 200, section)
        r = self.client.post(reverse('pipeline:edit_section', args=[self.a.pk, 'next']),
                             {'next_action': 'Send deck', 'next_action_owner': 'Sid', 'next_action_date': '2026-11-02'})
        self.assertEqual(r.status_code, 200)
        self.a.refresh_from_db()
        self.assertEqual((self.a.next_action, self.a.next_action_owner), ('Send deck', 'Sid'))

    def test_playbook_is_seeded_and_editable(self):
        from .models import UsageStage
        self.assertEqual(UsageStage.objects.count(), 5)
        r = self.client.get(reverse('pipeline:playbook'))
        self.assertContains(r, 'What healthy usage looks like')
        st = UsageStage.objects.first()
        r = self.client.post(reverse('pipeline:edit_usage_stage', args=[st.pk]),
                             {'name': 'Activated', 'window': 'First 3 days', 'healthy': 'x', 'credits': 'y', 'moves_on': 'z', 'gate': 'Gate: q'})
        self.assertEqual(r.status_code, 200)
        st.refresh_from_db()
        self.assertEqual(st.window, 'First 3 days')

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('pipeline:playbook')).status_code, 302)


class InlineToggleTests(SnapshotTests):
    def test_stage_chip_toggles_and_updates_score_and_path(self):
        url = reverse('pipeline:stage_toggle', args=[self.a.pk, 8])
        self.assertEqual(self.client.post(url).json()['anchor'], 'timeline-strip')
        self.assertEqual(Account.objects.get(pk=self.a.pk).score, 10)
        self.assertIn(8, Account.objects.get(pk=self.a.pk).done_stages)
        self.client.post(url)
        self.assertEqual(Account.objects.get(pk=self.a.pk).score, 0)

    def test_usage_flag_toggle_and_validation(self):
        url = reverse('pipeline:flag_toggle', args=[self.a.pk, 'usage_tried'])
        self.client.post(url)
        self.a.refresh_from_db()
        self.assertTrue(self.a.usage_tried)
        self.assertEqual(self.client.post(reverse('pipeline:flag_toggle', args=[self.a.pk, 'name'])).status_code, 404)
        self.assertEqual(self.client.get(url).status_code, 405)
