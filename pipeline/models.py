from urllib.parse import urlparse

from django.db import models

from .stages import STAGE_NAMES, STAGE_WEIGHTS, STAGES


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

    def stage_rows(self):
        by_stage = {p.stage: p for p in self.stage_progress.all()}
        rows = []
        for num, name in STAGES:
            p = by_stage.get(num)
            rows.append({
                'num': num, 'name': name, 'weight': STAGE_WEIGHTS[num],
                'done': bool(p and p.done), 'why': p.why if p else '',
            })
        return rows

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
