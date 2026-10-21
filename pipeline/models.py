import datetime
from urllib.parse import urlparse

from django.db import models

from .stages import PATH, STAGE_DAYS, STAGE_NAMES, STAGE_WEIGHTS, STAGES, USAGE_CHECKS


def normalize_domain(value):
    """'https://www.Acme.com/about' -> 'acme.com'"""
    value = value.strip().lower()
    if '://' not in value:
        value = 'https://' + value
    host = urlparse(value).hostname or ''
    return host.removeprefix('www.')


class Account(models.Model):
    # 1. Company
    name = models.CharField(max_length=200)
    domain = models.CharField(max_length=253, unique=True)
    deal_value = models.CharField(max_length=40, blank=True, help_text='e.g. $15K')

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

    @property
    def score_arc(self):
        """Length of the filled arc of the small donut (circumference 62.83 at r=10)."""
        return round(self.score / 100 * 62.83, 1)

    def stage_rows(self):
        by_stage = {p.stage: p for p in self.stage_progress.all()}
        rows = []
        for num, name in STAGES:
            p = by_stage.get(num)
            rows.append({
                'num': num, 'name': name, 'weight': STAGE_WEIGHTS[num],
                'done': bool(p and p.done), 'why': p.why if p else '',
                'target_date': p.target_date if p else None,
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
                    'gap': False, 'days': STAGE_DAYS[num], 'overdue': False}
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
        checks = [(key, label, bool(getattr(self, key)) or piloting) for key, label in USAGE_CHECKS]
        w = STAGE_WEIGHTS
        demo = 1.0 if 8 in done else sum(w[n] for n in done if n < 8) / sum(w[n] for n in range(1, 8))
        fractions = [
            demo,
            sum(1 for *_, ok in checks if ok) / len(checks),
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
        checks_ok = sum(1 for *_, ok in usage['checks'] if ok)
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
        cells = []
        for num, name in STAGES:
            if num in done:
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
    why = models.TextField(blank=True)
    target_date = models.DateField(null=True, blank=True)

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


# --- Tasks and next actions ---
class Task(models.Model):
    class Kind(models.TextChoices):
        TASK = 'task', 'Task'
        NEXT_ACTION = 'next_action', 'Next action'

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='tasks')
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.NEXT_ACTION)
    title = models.CharField(max_length=300)
    due_date = models.DateField()
    done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['done', 'due_date', 'id']


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
