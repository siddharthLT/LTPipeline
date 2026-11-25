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


class UsageVisualTests(Base):
    """Product usage shapes and the recordings tab, with PostHog answered from fixtures."""

    def test_replay_helpers(self):
        from . import posthog
        self.assertEqual(posthog.area_of('https://app.lunartree.bio/biolens/workspaces/5af5f95f-3b60-4e6b-b9ef-a050b72202b2/companies'), 'Workspace companies')
        self.assertEqual(posthog.area_of('https://app.lunartree.bio/login?next=/x'), 'Signing in')
        self.assertEqual(posthog.area_of('https://app.lunartree.bio/biolens'), 'Home')
        self.assertIsNone(posthog.area_of('https://app.lunartree.bio/somewhere/else'))
        self.assertEqual([posthog.bucket(s) for s in (5, 30, 119, 120, 599, 600, 1799, 1800, 99999)],
                         ['blip', 'short', 'short', 'mid', 'mid', 'long', 'long', 'deep', 'deep'])
        self.assertEqual(posthog._title([('Sent an email', 'act'), ('Viewed a company', 'view')], ['Home']), 'Sent an email · Viewed a company')
        self.assertEqual(posthog._title([], ['Signing in']), 'Sign-in only')
        self.assertEqual(posthog._title([], ['Signing in', 'Home']), 'Browsed Home')

    def test_duration_filters(self):
        from .templatetags.pipeline_extras import clock, spent
        self.assertEqual(clock(65), '1:05')
        self.assertEqual(clock(3729), '1:02:09')
        self.assertEqual(clock(170310), '47h 18m')
        self.assertEqual(spent(45), '45s')
        self.assertEqual(spent(720), '12 min')
        self.assertEqual(spent(11100), '3h 05m')

    def test_shape_counts_page_views_and_builds_strips(self):
        import datetime
        from . import posthog
        today = datetime.datetime.now(datetime.timezone.utc).date()
        day = today.isoformat()
        user = {'email': 'a@x.com', 'name': 'Ann Lee', 'evts': 3, 'sessions': 2, 'acts': 1, 'ai': 1, 'rage': 0, 'pvs': 12,
                'feats': 2, 'last_seen': day, 'profiles': 4, 'tier': posthog.tier({'acts': 1, 'feats': 2, 'evts': 3, 'pvs': 12})}
        self.assertEqual(user['tier'], 'Active')
        self.assertEqual(posthog.tier({'acts': 0, 'feats': 1, 'evts': 3, 'pvs': 12}), 'Browser')
        rows = [{'account': self.account, 'users': [user], 'evts': 3, 'sessions': 2, 'acts': 1, 'ai': 1, 'rage': 0, 'profiles': 4,
                 'last_seen': day, 'feats': 2}]
        counts = [1] + [0] * (len(posthog.ACTIONS) - 1)
        daily = [{'day': day, 'email': 'a@x.com', 'account': self.account, 'pvs': 12, 'counts': counts, 'total': 3}]
        sh = posthog.shape(rows, daily, 7)
        self.assertEqual(len(sh['series']), 8)
        self.assertEqual(sh['series'][-1]['total'], 15)  # 12 page views + 3 tracked events
        self.assertEqual(sh['series'][-1]['share'], 7)  # 1 of 15 is an action
        card = sh['cards'][0]
        self.assertEqual(card['active_days'], 1)
        self.assertGreaterEqual(card['strip'][-1]['lvl'], 1)
        self.assertEqual(card['people'][0]['ini'], 'AL')
        self.assertEqual(sh['features'][0]['label'], 'Company profiles read')

    def test_usage_tabs_render(self):
        import datetime
        from unittest import mock
        from . import posthog
        now = datetime.datetime.now(datetime.timezone.utc)
        day = now.date().isoformat()
        user = {'email': 'a@x.com', 'name': 'Ann Lee', 'evts': 3, 'sessions': 2, 'acts': 1, 'ai': 0, 'rage': 0, 'pvs': 5,
                'feats': 2, 'last_seen': day, 'profiles': 0, 'tier': 'Active'}
        rows = [{'account': self.account, 'users': [user], 'evts': 3, 'sessions': 2, 'acts': 1, 'ai': 0, 'rage': 0, 'profiles': 0,
                 'last_seen': day, 'feats': 2}]
        daily = [{'day': day, 'email': 'a@x.com', 'account': self.account, 'pvs': 5, 'counts': [0] * len(posthog.ACTIONS), 'total': 3}]
        totals = {'users': 1, 'matched_users': 1, 'evts': 3, 'acts': 1, 'ai': 0, 'rage': 0}
        rec = {'id': 'sess-1', 'url': 'https://us.posthog.com/project/1/replay/sess-1', 'email': 'a@x.com', 'name': 'Ann Lee', 'ini': 'AL',
               'country': 'India', 'browser': 'Chrome', 'os': 'Mac OS X', 'device': 'Desktop', 'start': now - datetime.timedelta(hours=2),
               'dur': 400, 'active': 60, 'clicks': 5, 'keys': 2, 'errors': 0, 'areas': ['Home'], 'pages': 3,
               'marks': [{'at': 10.5, 'kind': 'act'}, {'at': 50, 'kind': 'rage'}], 'did': ['Sent an email'], 'rage': 1,
               'title': 'Sent an email', 'bucket': 'mid', 'live': 15}
        self.account.domain = 'x.com'
        self.account.save()
        with mock.patch.object(posthog, 'join', return_value=(rows, [], daily, totals)), \
                mock.patch.object(posthog, 'recordings', return_value=[dict(rec)]):
            for tab in ('overview', 'accounts', 'users', 'daily', 'unmatched'):
                r = self.client.get(reverse('pipeline:usage') + '?tab=' + tab)
                self.assertEqual(r.status_code, 200, tab)
                self.assertNotContains(r, 'Could not load usage', msg_prefix=tab)
            r = self.client.get(reverse('pipeline:usage') + '?tab=recordings')
            self.assertContains(r, 'rec__thumb--mid')
            self.assertContains(r, 'https://us.posthog.com/project/1/replay/sess-1')
            self.assertContains(r, 'Sent an email')
            self.assertContains(r, '6:40')
            self.assertContains(r, 'mk--rage')
            self.assertContains(r, 'data-acct="%d"' % self.account.pk)


class MappedUniverseTests(Base):
    def setUp(self):
        super().setUp()
        from .models import MappedCompany
        rows = [(1, 'Alpha CRO', 'alpha.com', 'CRO', 'United States', 'Boston', 'MA'),
                (2, 'Beta Reagents', 'beta.com', 'Reagents', 'United States', 'Austin', 'TX'),
                (3, 'Gamma CDMO', 'gamma.de', 'CDMO', 'Germany', 'Berlin', ''),
                (4, 'Delta Packaging', '', 'Packaging', '', '', '')]
        from .models import world_region
        for i, name, dom, seg, country, city, state in rows:
            MappedCompany.objects.create(map_id=i, name=name, domain=dom, segment=seg, country=country, city=city, state=state,
                                         world_region=world_region(country), latitude=52.5 if i == 3 else None, longitude=13.4 if i == 3 else None,
                                         logo_url='https://example.com/l.png' if i == 1 else '')
        for i in range(5, 70):
            MappedCompany.objects.create(map_id=i, name='Filler %02d' % i, segment='CRO', country='United States')
        self.url = reverse('pipeline:mapped_universe')

    def names(self, r):
        return [c.name for c in r.context['page']]

    def test_list_is_paginated_and_shows_logo_or_initial(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['page']), 50)
        self.assertEqual(r.context['shown'], 70)
        self.assertContains(r, 'https://example.com/l.png')
        self.assertContains(r, 'logo__ini')
        self.assertEqual(len(self.client.get(self.url + '?page=2').context['page']), 20)

    def test_quick_filters(self):
        self.assertEqual(self.names(self.client.get(self.url + '?segment=CDMO')), ['Gamma CDMO'])
        self.assertEqual(sorted(self.names(self.client.get(self.url + '?segment=CDMO&segment=Reagents'))), ['Beta Reagents', 'Gamma CDMO'])
        self.assertEqual(self.names(self.client.get(self.url + '?region=Europe')), ['Gamma CDMO'])
        self.assertEqual(sorted(self.names(self.client.get(self.url + '?region=Unknown'))), ['Delta Packaging', 'OneSource'])
        self.assertEqual(self.names(self.client.get(self.url + '?country=Germany')), ['Gamma CDMO'])
        self.assertEqual(self.names(self.client.get(self.url + '?state=TX')), self.names(self.client.get(self.url)))  # ignored without a country
        us = self.url + '?country=United States'
        self.assertEqual(self.names(self.client.get(us + '&state=TX')), ['Beta Reagents'])
        self.assertEqual(sorted(self.names(self.client.get(us + '&state=TX&state=MA'))), ['Alpha CRO', 'Beta Reagents'])
        self.assertNotContains(self.client.get(self.url), 'US states')
        self.assertContains(self.client.get(us), 'US states')
        self.assertEqual(self.names(self.client.get(self.url + '?q=berlin')), ['Gamma CDMO'])
        self.assertEqual(self.names(self.client.get(self.url + '?q=alpha.com')), ['Alpha CRO'])
        self.assertNotIn('Alpha CRO', self.names(self.client.get(self.url + '?logo=no')))

    def test_map_view_has_points_and_shares_filters(self):
        r = self.client.get(self.url + '?view=map&region=Europe')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([p['n'] for p in r.context['points']], ['Gamma CDMO'])
        self.assertContains(r, 'mu-map')
        r = self.client.get(self.url + '?view=map')
        self.assertEqual(r.context['mapped'], 1)
        self.assertEqual(r.context['not_mapped'], 69)
        self.assertEqual(len(self.client.get(self.url + '?located=no').context['page']), 50)

    def test_suggest_dropdown(self):
        u = reverse('pipeline:mapped_suggest')
        self.assertEqual(self.client.get(u + '?q=a').json()['results'], [])
        names = [r['name'] for r in self.client.get(u + '?q=ga').json()['results']]
        self.assertEqual(names, ['Gamma CDMO'])
        self.assertEqual(len(self.client.get(u + '?q=filler').json()['results']), 8)
        self.assertEqual(self.client.get(u + '?q=filler&region=Europe').json()['results'], [])

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_import_rules(self):
        from .management.commands.import_mapped_universe import keep, name_key, root, host
        base = {'segment': 'Equipment', 'industry': ''}
        self.assertTrue(keep(dict(base, industry='research')))
        self.assertFalse(keep(dict(base, industry='medical devices')))
        self.assertFalse(keep({'segment': 'Pharma / Biotech', 'industry': ''}))
        self.assertFalse(keep({'segment': 'CRO', 'industry': 'information technology & services'}))
        self.assertTrue(keep({'segment': 'CDMO/CRO', 'industry': 'pharmaceuticals'}))
        self.assertEqual(root(host('https://www.Shilpabio.com/x')), 'shilpabio.com')
        self.assertEqual(root('bio.co.uk'), 'bio.co.uk')
        self.assertEqual(name_key('Acme Pharma, Inc.'), name_key('ACME'))


class MappedPipelineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('m@lunartree.bio', 'pw-123456')
        self.client.force_login(self.user)

    def test_new_account_joins_universe_once(self):
        from .models import MappedCompany
        a = Account.objects.create(name='Acme Bio', domain='acmebio.com', segment='cdmo')
        self.assertEqual(MappedCompany.objects.filter(domain='acmebio.com').count(), 1)
        from .models import ensure_mapped
        ensure_mapped(a)
        self.assertEqual(MappedCompany.objects.filter(domain='acmebio.com').count(), 1)

    def test_list_marks_pipeline_and_filters(self):
        from .models import MappedCompany
        a = Account.objects.create(name='Acme Bio', domain='acmebio.com', segment='cdmo')
        MappedCompany.objects.create(map_id=1, name='Other Co', domain='other.com', segment='CRO')
        r = self.client.get('/mapped-universe/')
        self.assertContains(r, 'Already in Pipeline')
        self.assertContains(r, 'data-fill-domain="other.com"')
        r = self.client.get('/mapped-universe/?pipe=out')
        self.assertNotContains(r, 'Already in Pipeline')
        r = self.client.get('/mapped-universe/?pipe=in')
        self.assertContains(r, 'Acme Bio')
        self.assertNotContains(r, 'Other Co')


class FunnelTests(TestCase):
    def test_build_orders_paths_and_counts_furthest_step(self):
        from datetime import datetime
        from unittest import mock
        from . import funnel
        t = lambda m: datetime(2026, 1, 1, 0, m)
        fake = {(234813, 'a@x.com'): {'visit': t(0), 'look': t(1), 'dig': t(2)},
                (234813, 'b@x.com'): {'visit': t(0), 'look': t(3), 'work': t(4), 'reach': t(5)},
                (600726, 'c@y.com'): {'visit': t(0)}}
        with mock.patch.object(funnel, 'users', return_value=fake):
            f = funnel.build([], 30)
            self.assertEqual([r['n'] for r in f['rows']], [3, 2, 2, 1, 1, 1])
            self.assertEqual(f['rows'][0]['stopped'], 1)
            self.assertTrue(f['sankey']['links'])
            self.assertEqual(f['total'], 3)

    def test_build_filters_to_one_account(self):
        from datetime import datetime
        from unittest import mock
        from . import funnel
        a = Account.objects.create(name='Acme', domain='x.com')
        Account.objects.create(name='Other', domain='y.com')
        t = lambda m: datetime(2026, 1, 1, 0, m)
        fake = {(234813, 'a@x.com'): {'visit': t(0), 'look': t(1)}, (600726, 'c@y.com'): {'visit': t(0)}}
        accounts = list(Account.objects.all())
        with mock.patch.object(funnel, 'users', return_value=fake):
            self.assertEqual({c['name'] for c in funnel.build(accounts, 30)['chips']}, {'Acme', 'Other'})
            f = funnel.build(accounts, 30, a.pk)
            self.assertEqual((f['total'], f['picked'].pk), (1, a.pk))
            self.assertEqual(funnel.build(accounts, 30, 99999)['total'], 2)


class DigestHealthTests(Base):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()

    def data(self):
        rows = [('Ann@onesource.com', '2026-11-23', 'digest_email_sent', None, 1), ('ann@onesource.com', '2026-11-24', 'digest_email_sent', None, 1),
                ('bob@onesource.com', '2026-11-23', 'digest_email_sent', None, 1), ('bob@onesource.com', '2026-11-24', 'digest_email_skipped', 'user_opted_out', 1),
                ('x@nowhere.org', '2026-11-24', 'digest_email_sent', None, 1)]
        return {'rows': rows, 'opened': {'ann@onesource.com': '2026-11-20T00:00:00Z'}}

    def test_build_marks_sent_and_skipped_and_never_opened(self):
        from unittest import mock
        from . import digests
        with mock.patch.object(digests, 'data', return_value=self.data()):
            d = digests.build([self.account], 30)
        c = d['cards'][0]
        self.assertEqual((c['sent'], c['skipped'], c['receiving'], c['never']), (3, 1, 2, 1))
        self.assertEqual([s['state'] for s in c['strip']], ['ok', 'ok'])
        people = {p['email']: p for p in c['people']}
        self.assertEqual((people['ann@onesource.com']['state'], people['bob@onesource.com']['state']), ('ok', 'bad'))
        self.assertEqual(people['bob@onesource.com']['why'], 'opted out')
        self.assertEqual(people['bob@onesource.com']['opened'], '')
        self.assertEqual(d['run_days'], 2)

    def test_tab_renders(self):
        from unittest import mock
        from . import digests
        with mock.patch.object(digests, 'data', return_value=self.data()):
            r = self.client.get(reverse('pipeline:usage') + '?tab=digests')
        self.assertContains(r, 'never opened')
        self.assertContains(r, 'dg__dot--bad')

    def test_digest_events_never_count_as_activity(self):
        from . import posthog
        self.assertIn("event NOT LIKE 'digest_email%'", posthog._where(30))


class MappedPeopleTests(Base):
    def setUp(self):
        super().setUp()
        from .models import MappedCompany, MappedPerson
        self.co = MappedCompany.objects.create(map_id=5, name='Zeta Labs', domain='zeta.com', segment='CRO', city='Boston', country='United States', state='MA')
        self.ann = MappedPerson.objects.create(company=self.co, domain='zeta.com', source_id=1, name='Ann Lee', title='VP Sales', email='ann@zeta.com',
                                               phone='+1 (555) 010-2000', linkedin_url='https://linkedin.com/in/ann', role='champion')
        self.bob = MappedPerson.objects.create(company=self.co, domain='zeta.com', source_id=2, name='Bob Ray', email='bob@zeta.com')

    def test_company_page_lists_people_with_buttons(self):
        r = self.client.get(reverse('pipeline:mapped_company', args=[self.co.pk]))
        self.assertContains(r, 'Zeta Labs')
        self.assertContains(r, 'Ann Lee')
        self.assertContains(r, 'href="https://linkedin.com/in/ann"')
        self.assertContains(r, 'href="mailto:ann@zeta.com"')
        self.assertContains(r, 'href="tel:+15550102000"')  # a call button only where there is a number
        self.assertNotContains(r, 'tel:' + 'None')
        self.assertContains(r, 'Add to pipeline')

    def test_warm_connections_are_tagged_and_filterable(self):
        from .models import MappedCompany
        self.ann.warm_via = 'Vedant, PK'
        self.ann.save()
        cold = MappedCompany.objects.create(map_id=6, name='Cold Co', domain='cold.com', segment='CRO')
        r = self.client.get(reverse('pipeline:mapped_company', args=[self.co.pk]))
        self.assertContains(r, 'Warm connection', count=2)  # the company tag and Ann's tag
        self.assertContains(r, 'via Vedant')
        self.assertContains(r, 'via PK')
        self.assertContains(self.client.get(reverse('pipeline:mapped_universe')), 'mu__nm mu__nm--warm', count=1)
        r = self.client.get(reverse('pipeline:mapped_universe') + '?warm=1')
        self.assertContains(r, 'Zeta Labs')
        self.assertNotContains(r, 'Cold Co')

    def test_company_in_pipeline_goes_to_its_thesis(self):
        a = Account.objects.create(name='Zeta', domain='zeta.com')
        r = self.client.get(reverse('pipeline:mapped_company', args=[self.co.pk]))
        self.assertRedirects(r, reverse('pipeline:account_detail', args=[a.pk]) + '#other-people', fetch_redirect_response=False)

    def test_thesis_shows_other_people_and_hides_those_already_named(self):
        a = Account.objects.create(name='Zeta', domain='zeta.com', champion='Ann Lee, VP Sales')
        r = self.client.get(reverse('pipeline:account_detail', args=[a.pk]))
        self.assertContains(r, 'Other people in company')
        self.assertContains(r, 'Bob Ray')
        self.assertNotContains(r, 'ann@zeta.com')  # already named as the champion

    def test_people_follow_a_company_that_joins_the_pipeline_even_if_its_row_goes(self):
        from .models import MappedCompany
        a = Account.objects.create(name='Zeta', domain='zeta.com')
        MappedCompany.objects.filter(pk=self.co.pk).delete()  # the old row can be replaced when a company joins
        self.assertContains(self.client.get(reverse('pipeline:account_detail', args=[a.pk])), 'Bob Ray')

    def test_import_command_adds_reliable_people_once(self):
        from io import StringIO
        from unittest import mock
        from django.core.management import call_command
        from .management.commands import import_mapped_people as cmd
        from .models import MappedPerson
        rows = [dict(id=10, name='Cy Dee', title='CEO', email='Cy@Zeta.com', phone='', linkedin='linkedin.com/in/cy', role='', company_id=5, site='zeta.com'),
                dict(id=11, name='Cy Dee', title='CEO', email='cy@zeta.com', phone='', linkedin='', role='', company_id=5, site='zeta.com'),  # same person twice
                dict(id=12, name='Lost Co', title='', email='x@nowhere.org', phone='', linkedin='', role='', company_id=99, site='nowhere.org')]
        with mock.patch.object(cmd, 'fetch', return_value=rows):
            call_command('import_mapped_people', stdout=StringIO())
            call_command('import_mapped_people', stdout=StringIO())  # re-running adds nothing
        cy = MappedPerson.objects.get(source_id=10)
        self.assertEqual((cy.email, cy.linkedin_url, cy.company_id), ('cy@zeta.com', 'https://linkedin.com/in/cy', self.co.pk))
        self.assertFalse(MappedPerson.objects.filter(source_id__in=[11, 12]).exists())
        self.assertEqual(MappedPerson.objects.count(), 3)


class AppModeTests(Base):
    """One codebase, two deployments: APP_MODE decides what each one serves."""

    def serve(self, mode):
        import importlib
        import sys
        from django.test import override_settings
        from django.urls import clear_url_caches
        ctx = override_settings(APP_MODE=mode, LOGIN_REDIRECT_URL='pipeline:usage' if mode == 'usage' else 'pipeline:dashboard')
        ctx.enable()
        self.addCleanup(self.restore, ctx)
        clear_url_caches()
        importlib.reload(sys.modules['pipeline.urls'])
        importlib.reload(sys.modules['config.urls'])

    def restore(self, ctx):
        import importlib
        import sys
        from django.urls import clear_url_caches
        ctx.disable()
        clear_url_caches()
        importlib.reload(sys.modules['pipeline.urls'])
        importlib.reload(sys.modules['config.urls'])

    def usage_page(self, tab='overview'):
        from unittest import mock
        from . import posthog
        totals = {'users': 0, 'matched_users': 0, 'evts': 0, 'acts': 0, 'ai': 0, 'rage': 0}
        with mock.patch.object(posthog, 'join', return_value=([], [], [], totals)):
            return self.client.get('/usage/?tab=' + tab)

    def test_usage_deployment_serves_only_usage(self):
        self.serve('usage')
        self.assertRedirects(self.client.get('/'), '/usage/', fetch_redirect_response=False)
        r = self.usage_page()
        self.assertContains(r, 'shell--solo')
        self.assertContains(r, 'Digest health')  # the views are in the sidebar
        self.assertContains(r, 'sidewin')  # and so is the window
        self.assertNotContains(r, 'Pending actions')
        self.assertNotContains(r, 'Scoring rules')
        for url in ('/actions/', '/rules/', '/health-check/', '/playbook/', '/mapped-universe/', '/accounts/%d/' % self.account.pk):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_usage_deployment_links_accounts_to_the_pipeline_deployment(self):
        from django.test import override_settings
        self.serve('usage')
        from django.template import Context, Template
        out = lambda: Template('{% load pipeline_extras %}{% account_url 7 %}').render(Context())
        self.assertEqual(out(), '#')
        with override_settings(PIPELINE_URL='https://pipe.example.com'):
            self.assertEqual(out(), 'https://pipe.example.com/accounts/7/')

    def test_pipeline_deployment_has_no_usage(self):
        self.serve('pipeline')
        r = self.client.get('/')
        self.assertNotContains(r, 'Product usage')
        self.assertContains(r, 'Scoring rules')
        self.assertEqual(self.client.get('/usage/').status_code, 404)
        self.assertEqual(self.client.get('/usage/live.json').status_code, 404)

    def test_default_deployment_serves_everything(self):
        self.serve('all')
        self.assertContains(self.client.get('/'), 'Product usage')
        self.assertEqual(self.usage_page().status_code, 200)
        self.assertNotContains(self.usage_page(), 'shell--solo')

    def test_login_pictures_differ(self):
        self.client.logout()
        self.serve('usage')
        self.assertContains(self.client.get('/accounts/login/'), 'data-usageviz')
        self.serve('pipeline')
        r = self.client.get('/accounts/login/')
        self.assertContains(r, 'data-globe')
        self.assertNotContains(r, 'data-usageviz')


class LiveUsersTests(Base):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.delete('posthog-live')

    def test_live_counts_people_across_projects_and_matches_account(self):
        from unittest import mock
        from . import posthog
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        rows = [('Ann Lee@Acme.com', 'Ann', now, 'https://app.x/biolens/companies/1', 's1')]
        Account.objects.create(name='Acme', domain='acme.com')
        with mock.patch.object(posthog, 'hql', return_value=rows):
            r = self.client.get(reverse('pipeline:usage_live'))
        data = r.json()
        self.assertEqual(data['count'], 1)  # the same person in both projects is counted once
        self.assertEqual(data['people'][0]['account'], 'Acme')
        self.assertEqual(data['people'][0]['area'], 'Company profile')

    def test_live_is_quiet_when_posthog_fails(self):
        from unittest import mock
        from . import posthog
        with mock.patch.object(posthog, 'hql', side_effect=OSError('down')):
            self.assertEqual(self.client.get(reverse('pipeline:usage_live')).json()['count'], 0)


class UsageInsightTests(Base):
    def stream(self, tab='funnel', content=None, days=30, **kw):
        import json
        from unittest import mock
        from . import insights
        content = content or {'headline': 'h', 'highlights': ['a'], 'insights': ['b'], 'outliers': [], 'risks': ['c']}
        evs = [{'t': 'delta', 'v': 'HEADLINE: h'}, {'t': 'done', 'content': content, 'provider': 'OpenAI'}]
        with mock.patch.object(insights, 'generate_stream', return_value=iter(evs)):
            r = self.client.post(reverse('pipeline:usage_insights'), dict({'tab': tab, 'days': days}, **kw))
            body = b''.join(r.streaming_content).decode() if r.streaming else ''  # the stream is lazy, so read it while patched
        return r, [json.loads(l) for l in body.splitlines()]

    def test_panel_is_folded_and_offers_expand_only_once_generated(self):
        from unittest import mock
        from . import posthog
        url = reverse('pipeline:usage') + '?tab=funnel'
        with mock.patch.object(posthog, 'hql', return_value=[]):
            fresh = self.client.get(url).content.decode()
            self.stream()
            done = self.client.get(url).content.decode()
        self.assertIn('Generate insights', fresh)
        self.assertRegex(fresh, r'data-insights-toggle[^>]*hidden')  # nothing to expand yet
        self.assertIn('New insights', done)
        self.assertNotRegex(done, r'data-insights-toggle[^>]*hidden')
        self.assertRegex(done, r'data-insights-body hidden')  # folded until someone clicks Expand

    def test_generate_streams_and_is_shared_and_replaced(self):
        from .models import UsageInsight
        r, evs = self.stream()
        self.assertEqual([e['t'] for e in evs], ['delta', 'done'])
        self.assertEqual(UsageInsight.objects.get(tab='funnel', days=30).generated_by, 'a@b.co')
        self.stream(content={'headline': 'second', 'highlights': ['a'], 'insights': [], 'outliers': [], 'risks': []})
        self.assertEqual(UsageInsight.objects.filter(tab='funnel', days=30).count(), 1)
        self.assertEqual(UsageInsight.objects.get(tab='funnel', days=30).content['headline'], 'second')
        self.assertContains(self.client.get(reverse('pipeline:usage') + '?tab=funnel'), 'second')

    def test_bad_tab_and_method(self):
        r, _ = self.stream(tab='nope')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get(reverse('pipeline:usage_insights')).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(reverse('pipeline:usage_insights'), {'tab': 'funnel'}).status_code, 302)

    def test_parse_and_fallback_to_groq(self):
        import os
        from unittest import mock
        from . import insights
        self.assertEqual(insights.parse('HEADLINE: x\nHIGHLIGHTS:\n- one\n  more\nRISKS:\n- r')['highlights'], ['one more'])
        good = 'HEADLINE: ok\nHIGHLIGHTS:\n- a\nINSIGHTS:\n- b'
        calls = []

        def fake(url, key, model, system, data):
            calls.append(url)
            if 'openai.com' in url:
                raise RuntimeError('answered 429')
            yield good
        env = {'OPENAI_KEY': 'o', 'GROQ_KEY': 'g'}
        with mock.patch.dict(os.environ, env), mock.patch.object(insights, '_stream', fake), mock.patch.object(insights, 'payload', return_value={}):
            evs = list(insights.generate_stream('funnel', [], 30))
        self.assertEqual([e['t'] for e in evs], ['reset', 'delta', 'done'])
        self.assertEqual(evs[-1]['provider'], 'Groq')
        self.assertEqual(len(calls), 2)
