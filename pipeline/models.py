import datetime
import re
from urllib.parse import urlparse

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from .stages import CRITERIA, PATH, STAGE_DAYS, STAGE_NAMES, STAGE_WEIGHTS, STAGES, USAGE_CHECKS


def normalize_domain(value):
    """'https://www.Acme.com/about' -> 'acme.com'"""
    value = value.strip().lower()
    if '://' not in value:
        value = 'https://' + value
    host = urlparse(value).hostname or ''
    return host.removeprefix('www.')


SEGMENTS = [
    ('cdmo', 'CDMO'),
    ('cro', 'CRO'),
    ('reagents', 'Reagents & formulation'),
    ('equipment', 'Equipment'),
    ('other', 'Other'),
]


class Account(models.Model):
    # 1. Company
    name = models.CharField(max_length=200)
    segment = models.CharField(max_length=12, choices=SEGMENTS, blank=True)
    domain = models.CharField(max_length=253, unique=True)
    logo_url = models.URLField(max_length=500, blank=True)
    deal_value = models.CharField(max_length=40, blank=True, help_text='e.g. $15K')
    sales_marketing_team = models.PositiveIntegerField(null=True, blank=True, help_text='People in sales and marketing (Apollo)')
    team_size_source = models.CharField(max_length=300, blank=True)
    advisors = models.CharField(max_length=200, blank=True, help_text='Advisors who connect us: Abhishek, Lavanya, Mak, PK, Naren')

    # 2. What they do, service, and who they service
    what_they_do = models.TextField(blank=True)
    what_they_service = models.TextField(blank=True)
    who_they_service = models.TextField(blank=True)

    # 3. Modality, focus area, phase, geography
    modality = models.TextField(blank=True)
    therapeutic_focus = models.TextField(blank=True)
    trial_phase = models.TextField(blank=True)
    geography = models.TextField(blank=True)

    # 4. Their ICP (one bullet per line)
    icp = models.TextField(blank=True)
    icp_source = models.CharField(max_length=300, blank=True)

    # Deal snapshot: who, what has to happen, risk, next action (bullet fields: one per line)
    buyer = models.TextField(blank=True)
    champion = models.TextField(blank=True)
    users = models.TextField(blank=True)
    blockers = models.TextField(blank=True)
    must_happen = models.TextField(blank=True)
    biggest_risk = models.TextField(blank=True)
    next_action = models.CharField(max_length=300, blank=True)
    next_action_owner = models.CharField(max_length=100, blank=True)
    next_action_date = models.DateField(null=True, blank=True)

    # Usage checks that drive the path after a demo
    usage_tried = models.BooleanField(default=False)
    usage_value = models.BooleanField(default=False)
    usage_onboarded = models.BooleanField(default=False)
    integration_started = models.BooleanField(default=False)

    # Short buying thesis
    why_buy = models.TextField(blank=True)
    pain_now = models.TextField(blank=True)
    who_cares = models.TextField(blank=True)
    buying_first = models.TextField(blank=True)
    before_pay = models.TextField(blank=True)
    expand_when = models.TextField(blank=True)
    why_not = models.TextField(blank=True)

    # Commercial path (dates left empty use the predicted date for that stage)
    trial_note = models.CharField(max_length=300, blank=True)
    expected_credits = models.CharField(max_length=200, blank=True)
    pilot_value = models.CharField(max_length=200, blank=True)
    pilot_date = models.DateField(null=True, blank=True)
    annual_value = models.CharField(max_length=200, blank=True)
    annual_date = models.DateField(null=True, blank=True)
    expansion_trigger = models.CharField(max_length=300, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        creating = self._state.adding
        super().save(*args, **kwargs)
        if creating:
            StageProgress.objects.bulk_create(
                [StageProgress(account=self, stage=num) for num, _ in STAGES]
            )

    # --- 5. Stage tracker and score ---
    @property
    def done_stages(self):
        return {p.stage for p in self.stage_progress.all() if p.done}

    @property
    def score(self):
        return sum(STAGE_WEIGHTS[s] for s in self.done_stages)

    @property
    def furthest_stage(self):
        return max(self.done_stages, default=0)

    @property
    def furthest_stage_name(self):
        return STAGE_NAMES.get(self.furthest_stage, 'Not started')

    def open_actions(self):
        return [t for t in self.tasks.all() if not t.done]

    def overdue_actions(self, today=None):
        today = today or datetime.date.today()
        return [t for t in self.open_actions() if t.due_date and t.due_date < today]

    @property
    def score_arc(self):
        """Length of the filled arc of the small donut (circumference 62.83 at r=10)."""
        return round(self.score / 100 * 62.83, 1)

    def stage_rows(self):
        by_stage = {p.stage: p for p in self.stage_progress.all()}
        rows = []
        for num, name in STAGES:
            p = by_stage.get(num)
            met = set(p.criteria) if p else set()
            crit = [{'key': k, 'label': label, 'met': k in met} for k, label in CRITERIA[num]]
            rows.append({
                'num': num, 'name': name, 'weight': STAGE_WEIGHTS[num],
                'done': bool(p and p.done), 'why': p.why if p else '',
                'target_date': p.target_date if p else None,
                'criteria': crit, 'met': sum(c['met'] for c in crit), 'total': len(crit),
            })
        return rows

    # --- Predicted timeline ---
    def schedule(self, today=None):
        """Predicted date for every open step.

        Steps ahead of the furthest done step run one after another from today, each taking its typical
        STAGE_DAYS. Open steps behind it are gaps and are assumed to be closed in parallel. A target date
        set on a step replaces its predicted date and moves the steps after it.
        """
        today = today or datetime.date.today()
        rows = {r['num']: r for r in self.stage_rows()}
        furthest = self.furthest_stage
        cursor = today
        out = []
        for num, name in STAGES:
            r = rows[num]
            item = {'num': num, 'name': name, 'done': r['done'], 'date': None, 'override': False,
                    'gap': False, 'days': STAGE_DAYS[num], 'overdue': False,
                    'met': r['met'], 'total': r['total']}
            if not r['done']:
                target = r['target_date']
                if num < furthest:
                    item['gap'] = True
                    item['date'] = target or today + datetime.timedelta(days=STAGE_DAYS[num])
                else:
                    cursor = max(target, today) if target else cursor + datetime.timedelta(days=STAGE_DAYS[num])
                    item['date'] = target or cursor
                item['override'] = bool(target)
                item['overdue'] = item['date'] < today
            out.append(item)
        return out

    @property
    def next_stage(self):
        """First open step after the furthest done one."""
        return next((s for s in self.schedule() if not s['done'] and s['num'] > self.furthest_stage), None)

    def path_steps(self):
        """Demo -> real usage -> pilot -> annual contract -> integration, each 0..1, from the stage ticks."""
        done = self.done_stages
        piloting = 10 in done or 11 in done or 12 in done
        checks = [{'key': key, 'label': label, 'manual': bool(getattr(self, key)), 'ok': bool(getattr(self, key)) or piloting}
                  for key, label in USAGE_CHECKS]
        w = STAGE_WEIGHTS
        demo = 1.0 if 8 in done else sum(w[n] for n in done if n < 8) / sum(w[n] for n in range(1, 8))
        fractions = [
            demo,
            sum(1 for c in checks if c['ok']) / len(checks),
            sum(1 for n in (10, 11) if n in done) / 2,
            1.0 if 12 in done else 0.0,
            1.0 if self.integration_started else 0.0,
        ]
        steps = []
        current_marked = False
        for (name, drivers), frac in zip(PATH, fractions):
            if frac >= 1:
                state = 'done'
            elif not current_marked:
                state, current_marked = 'now', True
            else:
                state = 'todo'
            steps.append({'name': name, 'drivers': drivers, 'fraction': frac, 'pct': round(frac * 100), 'state': state})
        steps[1]['checks'] = checks
        return steps

    @property
    def path_pct(self):
        steps = self.path_steps()
        return round(sum(s['fraction'] for s in steps) / len(steps) * 100)

    def commercial_nodes(self):
        """The five points on the commercial path with date and value at each."""
        sched = {s['num']: s for s in self.schedule()}

        def when(num, override=None):
            s = sched[num]
            if s['done']:
                return {'date': None, 'label': 'Done', 'auto': False}
            if override:
                return {'date': override, 'label': '', 'auto': False}
            return {'date': s['date'], 'label': '', 'auto': True}

        usage = self.path_steps()[1]
        checks_ok = sum(1 for c in usage['checks'] if c['ok'])
        usage_when = ({'date': None, 'label': 'Done', 'auto': False} if usage['state'] == 'done'
                      else {'date': None, 'label': f'{checks_ok} of {len(usage["checks"])} checks', 'auto': False, 'plain': True})
        return [
            {'name': 'Demo', 'value': '', 'empty': '', 'note': '', **when(8)},
            {'name': 'Real usage', 'value': self.expected_credits, 'empty': 'Expected usage not set', 'note': self.trial_note, **usage_when},
            {'name': 'Pilot', 'value': self.pilot_value, 'empty': 'Value not set', 'note': '', **when(10, self.pilot_date)},
            {'name': 'Annual contract', 'value': self.annual_value or self.deal_value, 'empty': 'Value not set', 'note': '', **when(12, self.annual_date)},
            {'name': 'Integration / expansion', 'value': '', 'empty': '', 'note': self.expansion_trigger,
             'date': None, 'label': 'After contract', 'auto': False, 'plain': True},
        ]

    def gantt_cells(self):
        done = self.done_stages
        furthest = max(done, default=0)
        started = {r['num'] for r in self.stage_rows() if r['met'] and not r['done']}
        cells = []
        for num, name in STAGES:
            if num in started:
                cells.append({'num': num, 'name': name, 'state': 'part'})
            elif num in done:
                cells.append({
                    'num': num, 'name': name,
                    'state': 'now' if num == furthest else 'done',
                    'cap_l': (num - 1) not in done, 'cap_r': (num + 1) not in done,
                })
            else:
                cells.append({'num': num, 'name': name, 'state': None})
        return cells


class StageProgress(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='stage_progress')
    stage = models.PositiveSmallIntegerField()
    done = models.BooleanField(default=False)
    why = models.TextField(blank=True, help_text='Evidence for the criteria')
    target_date = models.DateField(null=True, blank=True)
    criteria = models.JSONField(default=list, blank=True, help_text='Keys of the criteria that are met')

    class Meta:
        ordering = ['stage']
        constraints = [models.UniqueConstraint(fields=['account', 'stage'], name='uniq_account_stage')]


# --- 6. Meeting notes ---
MEETING_PARTS = [
    ('who', 'Who was on the call'),
    ('problems', 'Named problems they told us'),
    ('tools', 'Tools and workflows they use today'),
    ('showed', 'What we showed them'),
    ('questions', 'Follow-up questions they asked us'),
    ('landed', 'Where we landed well'),
    ('pushback', 'Where we could not help, or they pushed back'),
]


class MeetingNote(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='meetings')
    title = models.CharField(max_length=200)
    held_on = models.DateField(null=True, blank=True)
    who = models.TextField(blank=True)
    problems = models.TextField(blank=True)
    tools = models.TextField(blank=True)
    showed = models.TextField(blank=True)
    questions = models.TextField(blank=True)
    landed = models.TextField(blank=True)
    pushback = models.TextField(blank=True)

    class Meta:
        ordering = ['-held_on', '-id']

    def __str__(self):
        return self.title

    @property
    def parts(self):
        return [(key, label, getattr(self, key)) for key, label in MEETING_PARTS]


# --- 7. Timeline and sent emails ---
class TimelineEvent(models.Model):
    class Kind(models.TextChoices):
        CALL = 'call', 'Call'
        EMAIL = 'email', 'Email'
        WHATSAPP = 'whatsapp', 'WhatsApp'
        MEETING = 'meeting', 'Meeting'
        OTHER = 'other', 'Other'

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='events')
    date = models.DateField()
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.EMAIL)
    text = models.TextField()

    class Meta:
        ordering = ['date', 'id']


class SentEmail(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='emails')
    sent_on = models.DateField()
    subject = models.CharField(max_length=300)
    recipients = models.CharField(max_length=500, blank=True, help_text='To / cc / context')
    body = models.TextField(blank=True)

    class Meta:
        ordering = ['sent_on', 'id']


# --- Next actions: any number per account, each with an owner and an optional date ---
class Task(models.Model):
    class Kind(models.TextChoices):
        TASK = 'task', 'Task'
        NEXT_ACTION = 'next_action', 'Next action'

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='tasks')
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.NEXT_ACTION)  # unused, kept for old rows
    title = models.CharField(max_length=300)
    owner = models.CharField(max_length=100, blank=True)
    due_date = models.DateField(null=True, blank=True)
    done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['done', models.F('due_date').asc(nulls_last=True), 'id']


# --- Usage playbook: what healthy usage looks like at each stage, and where to gate or guide ---
class UsageStage(models.Model):
    order = models.PositiveSmallIntegerField(unique=True)
    name = models.CharField(max_length=100)
    window = models.CharField(max_length=100, blank=True)
    healthy = models.TextField(blank=True, help_text='Behaviour that tells us usage is healthy')
    credits = models.CharField(max_length=300, blank=True)
    moves_on = models.TextField(blank=True)
    gate = models.TextField(blank=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.name


EUROPE = {'Germany', 'Switzerland', 'France', 'United Kingdom', 'Spain', 'Italy', 'Ireland', 'Sweden', 'Netherlands', 'Belgium', 'Denmark',
          'Poland', 'Estonia', 'Austria', 'Hungary', 'Slovakia', 'Greece', 'Norway', 'Finland', 'Portugal', 'Czechia', 'Czech Republic',
          'Lithuania', 'Latvia', 'Slovenia', 'Croatia', 'Romania', 'Bulgaria', 'Iceland', 'Luxembourg', 'Malta', 'Serbia', 'Ukraine'}
ASIA_PACIFIC = {'China', 'Japan', 'South Korea', 'India', 'Australia', 'Taiwan', 'Singapore', 'Hong Kong', 'New Zealand', 'Thailand',
                'Malaysia', 'Indonesia', 'Vietnam', 'Philippines', 'Pakistan', 'Bangladesh', 'Sri Lanka'}
MIDDLE_EAST_AFRICA = {'Israel', 'South Africa', 'United Arab Emirates', 'Saudi Arabia', 'Egypt', 'Turkey', 'Qatar', 'Jordan', 'Kenya', 'Nigeria', 'Morocco'}
LATIN_AMERICA = {'Brazil', 'Argentina', 'Chile', 'Colombia', 'Peru', 'Uruguay', 'Costa Rica', 'Panama'}
WORLD_REGIONS = ['US West', 'US East', 'US Central', 'US (state unknown)', 'Canada & Mexico', 'Europe', 'Asia-Pacific', 'Middle East & Africa', 'Latin America', 'Other', 'Unknown']


def world_region(country, us_region=''):
    """Region a company belongs to, from its country (and the Company Map's west/east split for the US)."""
    if not country:
        return 'Unknown'
    if country == 'United States':
        return {'west': 'US West', 'east': 'US East', 'other': 'US Central'}.get(us_region, 'US (state unknown)')
    for name, group in (('Canada & Mexico', {'Canada', 'Mexico'}), ('Europe', EUROPE), ('Asia-Pacific', ASIA_PACIFIC),
                        ('Middle East & Africa', MIDDLE_EAST_AFRICA), ('Latin America', LATIN_AMERICA)):
        if country in group:
            return name
    return 'Other'


class MappedCompany(models.Model):
    """The mapped universe: every relevant CDMO, CRO, reagent, equipment and packaging company, in the pipeline or not.
    A company is in the pipeline when an Account has the same domain."""
    map_id = models.PositiveBigIntegerField(unique=True, help_text='id in the Company Map database this row came from')
    name = models.CharField(max_length=200)
    domain = models.CharField(max_length=253, blank=True, db_index=True)
    url = models.URLField(max_length=500, blank=True)
    logo_url = models.URLField(max_length=500, blank=True)
    segment = models.CharField(max_length=40, db_index=True)
    sub_type = models.CharField(max_length=200, blank=True)
    product_category = models.TextField(blank=True)
    address = models.CharField(max_length=300, blank=True, help_text='Street address as held in the Company Map')
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=60, blank=True)
    state_name = models.CharField(max_length=80, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=80, blank=True, db_index=True)
    world_region = models.CharField(max_length=24, blank=True, db_index=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    geo_source = models.CharField(max_length=12, blank=True, help_text="'source' came with the Company Map, 'address' and 'city' were geocoded")
    employee_count = models.PositiveIntegerField(null=True, blank=True)
    linkedin_url = models.URLField(max_length=500, blank=True)
    source = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'mapped companies'

    def __str__(self):
        return self.name


class MappedPerson(models.Model):
    """A person at a mapped company, copied from the Company Map's contact database.
    Kept by the company's domain as well as the row, so the person is still found when the company joins the pipeline
    (its mapped row can be replaced then) and shows under 'Other people in company' on the buying thesis."""
    company = models.ForeignKey(MappedCompany, null=True, blank=True, on_delete=models.SET_NULL, related_name='people')
    domain = models.CharField(max_length=253, blank=True, db_index=True, help_text="The company's domain, as on the mapped row")
    source_id = models.PositiveBigIntegerField(unique=True, help_text='id of the person in the Company Map database')
    name = models.CharField(max_length=200)
    title = models.CharField(max_length=300, blank=True)
    email = models.EmailField(max_length=254, blank=True)
    phone = models.CharField(max_length=60, blank=True)
    linkedin_url = models.URLField(max_length=500, blank=True)
    role = models.CharField(max_length=30, blank=True, help_text='decision_maker, champion, influencer or end_user, when known')
    warm_via = models.CharField(max_length=200, blank=True, help_text='Who on our side knows them, comma separated (a warm connection when set)')

    ROLE_ORDER = {'decision_maker': 0, 'champion': 1, 'influencer': 2, 'end_user': 3}
    ROLE_LABELS = {'decision_maker': 'Decision maker', 'champion': 'Champion', 'influencer': 'Influencer', 'end_user': 'End user'}

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'mapped people'

    def __str__(self):
        return self.name

    @property
    def role_label(self):
        return self.ROLE_LABELS.get(self.role, '')

    @property
    def warm_names(self):
        return [x.strip() for x in self.warm_via.split(',') if x.strip()]

    @property
    def tel(self):
        return re.sub(r'[^0-9+]', '', self.phone)


def people_for(domain, company=None, hide_text=''):
    """People at a company, found by its row and by its domain. Named people already written into hide_text (matched on email or full name) are left out.
    Warm connections come first, then those with a role."""
    from django.db.models import Q
    keys = set()
    if domain:
        d = re.sub(r'^https?://', '', domain.strip().lower())
        d = re.sub(r'^www\.', '', d).split('/')[0]
        parts = d.split('.')
        keys |= {d, '.'.join(parts[-3:]) if len(parts) >= 3 and parts[-2] in ('co', 'com', 'org') else '.'.join(parts[-2:])}
    q = Q(domain__in=keys) if keys else Q(pk__in=[])
    if company is not None:
        q |= Q(company=company)
    out, seen, text = [], set(), (hide_text or '').lower()
    for person in MappedPerson.objects.filter(q).order_by('name'):
        if person.pk in seen:
            continue
        seen.add(person.pk)
        if text and ((person.email and person.email.lower() in text) or (len(person.name) >= 5 and person.name.lower() in text)):
            continue
        out.append(person)
    out.sort(key=lambda x: (not x.warm_via, MappedPerson.ROLE_ORDER.get(x.role, 9), x.name.lower()))
    return out


PIPELINE_ID_BASE = 3_000_000_000  # map_id for pipeline accounts: base + account id (Company Map and sheet ids are lower)
SEGMENT_LABELS = {'cdmo': 'CDMO', 'cro': 'CRO', 'reagents': 'Reagents', 'equipment': 'Equipment', 'other': 'Other'}


def ensure_mapped(account):
    """Make sure a pipeline account has a row in the mapped universe (matched on domain, so never twice)."""
    existing = MappedCompany.objects.filter(domain=account.domain).first()
    if existing:
        return existing
    return MappedCompany.objects.create(
        map_id=PIPELINE_ID_BASE + account.pk, name=account.name, domain=account.domain, url='https://' + account.domain,
        logo_url=account.logo_url, segment=SEGMENT_LABELS.get(account.segment, 'Other'), source='Pipeline',
        world_region='Unknown')


@receiver(post_save, sender=Account)
def _mapped_for_new_account(sender, instance, created, **kwargs):
    if created and instance.domain:
        ensure_mapped(instance)


class UsageInsight(models.Model):
    """The latest AI summary for one Product usage tab and window. Shared by every user until someone generates a new one."""
    tab = models.CharField(max_length=20)
    days = models.PositiveSmallIntegerField()
    content = models.JSONField(default=dict)
    generated_by = models.CharField(max_length=254, blank=True)
    generated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('tab', 'days')]

    def __str__(self):
        return '%s (%dd)' % (self.tab, self.days)


class Campaign(models.Model):
    """An outreach campaign: an audience, a short brief and an ordered list of steps to tick off per person."""
    TAGS = [('gtm', 'GTM / CS'), ('hiring', 'Hiring outreach')]
    name = models.CharField(max_length=160)
    tag = models.CharField(max_length=10, choices=TAGS, default='gtm')
    brief = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['tag', 'created_at', 'pk']

    def __str__(self):
        return self.name

    @property
    def tag_label(self):
        return dict(self.TAGS).get(self.tag, self.tag)


class CampaignStep(models.Model):
    KINDS = [('li_connect', 'LinkedIn Connect Request'), ('li_dm', 'LinkedIn DM'), ('email', 'Email'), ('call', 'Call'), ('other', 'Other Manual task')]
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='steps')
    position = models.PositiveSmallIntegerField(default=0)
    kind = models.CharField(max_length=12, choices=KINDS, default='email')
    subject = models.CharField(max_length=300, blank=True)  # email steps: the subject line
    note = models.TextField(blank=True)  # the task note; for an email, its copy
    wait_days = models.PositiveSmallIntegerField(default=0)  # days after the step before

    class Meta:
        ordering = ['position', 'pk']

    @property
    def kind_label(self):
        return dict(self.KINDS).get(self.kind, self.kind)


class CampaignPerson(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='people')
    position = models.PositiveIntegerField(default=0)
    name = models.CharField(max_length=160)
    title = models.CharField(max_length=300, blank=True)
    company = models.CharField(max_length=160, blank=True)
    email = models.CharField(max_length=254, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    linkedin_url = models.URLField(max_length=500, blank=True)
    note = models.TextField(blank=True)
    done = models.ManyToManyField(CampaignStep, through='StepDone', related_name='done_by')

    class Meta:
        ordering = ['position', 'pk']

    @property
    def tel(self):
        return re.sub(r'[^\d+]', '', self.phone)


class StepDone(models.Model):
    person = models.ForeignKey(CampaignPerson, on_delete=models.CASCADE)
    step = models.ForeignKey(CampaignStep, on_delete=models.CASCADE)
    done_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('person', 'step')]
