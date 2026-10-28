import datetime

from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from .models import Account, MeetingNote, SentEmail, TimelineEvent, normalize_domain
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
        for p in self.account.stage_progress.all():
            p.done = True
            p.save()
        self.assertEqual(Account.objects.get(pk=self.account.pk).score, 100)


class ThesisTests(Base):
    def post(self, url, data):
        return self.client.post(url, data)

    def test_detail_renders(self):
        r = self.client.get(reverse('pipeline:account_detail', args=[self.account.pk]))
        self.assertContains(r, 'Buying thesis')
        self.assertContains(r, 'On this page')
        self.assertNotContains(r, 'Tasks and next actions')

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

    def test_step_is_done_only_when_all_criteria_are_met(self):
        from .stages import CRITERIA
        url = reverse('pipeline:stage_edit', args=[self.account.pk, 4])
        keys = [k for k, _ in CRITERIA[4]]
        partial = {f'c_{k}': 'on' for k in keys[:-1]}
        partial['why'] = 'evidence'
        self.assertEqual(self.post(url, partial).status_code, 200)
        a = Account.objects.get(pk=self.account.pk)
        self.assertEqual(a.score, 0)
        row = [r for r in a.stage_rows() if r['num'] == 4][0]
        self.assertEqual((row['met'], row['total'], row['done']), (len(keys) - 1, len(keys), False))
        self.assertEqual(a.gantt_cells()[3]['state'], 'part')
        self.assertEqual(self.post(url, {f'c_{k}': 'on' for k in keys}).status_code, 200)
        a = Account.objects.get(pk=self.account.pk)
        self.assertEqual(a.score, 5)
        self.assertEqual(a.gantt_cells()[3]['state'], 'now')
        self.post(url, {f'c_{keys[0]}': 'on'})  # untick two criteria: done again becomes false
        self.assertEqual(Account.objects.get(pk=self.account.pk).score, 0)

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
        from .stages import CRITERIA
        for p in self.a.stage_progress.filter(stage__in=nums):
            p.done, p.criteria = True, [k for k, _ in CRITERIA[p.stage]]
            p.save()

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
        for section in ['people', 'move', 'usage', 'why', 'first', 'before', 'expand', 'commercial', 'whynot']:
            self.assertEqual(self.client.get(reverse('pipeline:edit_section', args=[self.a.pk, section])).status_code, 200, section)

    def test_next_actions_add_many_toggle_delete(self):
        from .models import Task
        pk = self.a.pk
        new = reverse('pipeline:item_new', args=[pk, 'action'])
        self.assertEqual(self.client.post(new, {'title': 'Send deck', 'owner': 'Sid', 'due_date': '2026-11-02'}).status_code, 200)
        self.assertEqual(self.client.post(new, {'title': 'Book Rob call'}).status_code, 200)  # owner and date optional
        self.assertEqual(self.client.post(new, {'title': ''}).status_code, 400)
        self.assertEqual(Task.objects.filter(account=self.a).count(), 2)
        t = Task.objects.get(title='Send deck')
        r = self.client.get(reverse('pipeline:account_detail', args=[pk]))
        self.assertContains(r, 'Send deck')
        self.assertContains(r, 'Book Rob call')
        self.client.post(reverse('pipeline:action_toggle', args=[pk, t.pk]))
        t.refresh_from_db()
        self.assertTrue(t.done)
        self.assertEqual(len(self.a.open_actions()), 1)
        self.client.post(reverse('pipeline:item_delete', args=[pk, 'action', t.pk]))
        self.assertEqual(Task.objects.filter(account=self.a).count(), 1)
        other = Account.objects.create(name='O', domain='o.io')
        ot = Task.objects.create(account=other, title='x')
        self.assertEqual(self.client.post(reverse('pipeline:action_toggle', args=[pk, ot.pk])).status_code, 404)

    def test_pending_actions_panel_lists_open_actions_across_accounts(self):
        from .models import Task
        other = Account.objects.create(name='Zed Bio', domain='zed.io')
        Task.objects.create(account=self.a, title='Send deck', owner='Sid')
        Task.objects.create(account=other, title='Call Zed', owner='Vedant', due_date=datetime.date(2026, 11, 3))
        Task.objects.create(account=other, title='Old thing', done=True)
        r = self.client.get(reverse('pipeline:dashboard'))
        for text in ('Pending actions', 'Send deck', 'Call Zed', 'Zed Bio', 'Vedant'):
            self.assertContains(r, text)
        self.assertNotContains(r, 'Old thing')

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
    def test_stage_modal_renders_and_rules_page(self):
        self.assertEqual(self.client.get(reverse('pipeline:stage_edit', args=[self.a.pk, 8])).status_code, 200)
        self.assertEqual(self.client.get(reverse('pipeline:stage_edit', args=[self.a.pk, 99])).status_code, 404)
        r = self.client.get(reverse('pipeline:rules'))
        self.assertContains(r, 'Done when all of these are true')
        self.assertContains(r, 'Contract signed')

    def test_usage_flag_toggle_and_validation(self):
        url = reverse('pipeline:flag_toggle', args=[self.a.pk, 'usage_tried'])
        self.client.post(url)
        self.a.refresh_from_db()
        self.assertTrue(self.a.usage_tried)
        self.assertEqual(self.client.post(reverse('pipeline:flag_toggle', args=[self.a.pk, 'name'])).status_code, 404)
        self.assertEqual(self.client.get(url).status_code, 405)


class ForecastTests(TestCase):
    def test_parse_arr(self):
        from .forecast import parse_arr
        self.assertEqual(parse_arr('$30K'), 30000)
        self.assertEqual(parse_arr('$12-25K'), 18500)
        self.assertEqual(parse_arr('$1.2M'), 1200000)
        self.assertIsNone(parse_arr(''))

    def test_close_probability(self):
        from .forecast import close_probability
        self.assertAlmostEqual(close_probability(15, 0.2), 0.2)      # just had the first call
        self.assertAlmostEqual(close_probability(100, 0.2), 1.0)
        self.assertAlmostEqual(close_probability(0, 0.2), 0.0)
        self.assertLess(close_probability(5, 0.2), 0.2)              # before the first call
        self.assertGreater(close_probability(50, 0.2), 0.2)

    def _acct(self, name, score, val, days, team=None, advisors='', text='', done=False):
        import datetime
        from types import SimpleNamespace as NS
        today = datetime.date(2026, 10, 27)
        return NS(name=name, score=score, deal_value=val, sales_marketing_team=team, advisors=advisors, signal_text=text,
                  contract_info={'done': done, 'date': today + datetime.timedelta(days=days)})

    def test_predict_tier(self):
        from .forecast import predict_tier
        tier = lambda **kw: predict_tier(self._acct('A', 10, kw.pop('val', ''), 100, **kw), kw.get('done', False))
        self.assertEqual(tier(team=5)[0]['name'], 'Starter')
        self.assertEqual(tier(team=40)[0]['name'], 'Growth')
        self.assertEqual(tier(team=400)[1], 72000)
        self.assertEqual(tier(team=5, text='wants Salesforce sync')[0]['name'], 'Growth')
        self.assertEqual(tier(team=5, text='needs a dedicated instance')[0]['name'], 'Enterprise')
        self.assertEqual(tier(team=5, val='$20K')[1], 36000)         # nothing below Starter
        self.assertEqual(tier(team=5, val='$60K')[1], 60000)         # a real estimate of $36K or more wins
        arr = predict_tier(self._acct('S', 100, '$45K', 0, team=3), True)
        self.assertEqual((arr[0]['name'], arr[1]), ('Growth', 45000))

    def test_build_timing_and_tiers(self):
        import datetime
        from .forecast import build, advisor_names
        today = datetime.date(2026, 10, 27)
        self.assertEqual(advisor_names('Mak and PK, not Madhu'), ['Mak', 'PK'])
        warm = self._acct('Warm', 15, '', 135, team=300, advisors='Mak')
        cold = self._acct('Cold', 15, '', 135, team=5)
        out = build([warm, cold], today, cycle_months=3, conversion=0.5)
        by = {e['name']: e for e in out['entries']}
        # large team with an advisor keeps the 91 day cycle plus the Enterprise security review; small team, no advisor is slower
        self.assertEqual((by['Warm']['date'] - today).days, 91 + 45)
        self.assertGreater(by['Cold']['date'], by['Warm']['date'])
        self.assertEqual((by['Warm']['tier'], by['Cold']['tier']), ('Enterprise', 'Starter'))
        pts = out['points']
        self.assertEqual(len(pts), 19)
        self.assertEqual(pts[0]['accounts'], 0)
        self.assertEqual(pts[18]['accounts'], 1)                      # 2 x 0.5 = 1 account, the likelier is chosen
        self.assertEqual(pts[18]['by_tier']['enterprise'] + pts[18]['by_tier']['starter'], pts[18]['arr'])
        arr = [p['arr'] for p in pts]
        self.assertEqual(arr, sorted(arr))
        done = build([self._acct('Live', 100, '$45K', 0, done=True)], today)
        self.assertEqual(done['signed'], ['Live'])
        self.assertEqual(done['points'][0]['arr'], 45000)

    def test_cold_accounts_queue_least_ready_last(self):
        import datetime
        from .forecast import build
        today = datetime.date(2026, 10, 27)
        accts = [self._acct('C%02d' % i, 0, '', 135, team=5) for i in range(13)]
        accts.append(self._acct('Advised', 0, '', 135, team=5, advisors='PK'))
        by = {e['name']: e['date'] for e in build(accts, today)['entries']}
        self.assertEqual(by['Advised'], min(by.values()))                 # the advised account starts first
        self.assertGreater(max(by.values()), min(by.values()) + datetime.timedelta(days=30))   # the rest are spread out

    def test_dashboard_shows_forecast(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user(email='f@x.io', password='pw-123456')
        self.client.force_login(user)
        Account.objects.create(name='A', domain='a.com')
        self.assertContains(self.client.get('/'), 'id="arr-data"')
