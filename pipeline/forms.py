import re

from django import forms

from .models import MEETING_PARTS, Account, MeetingNote, SentEmail, Task, TimelineEvent, UsageStage, normalize_domain
from .stages import STAGES, STAGE_WEIGHTS

DOMAIN_RE = re.compile(r'^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$')


class StyledMixin:
    """Apply design-system classes to every widget."""

    def _style(self):
        for field in self.fields.values():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                continue
            if isinstance(w, forms.Textarea):
                w.attrs.setdefault('rows', 4)
                w.attrs['class'] = 'textarea'
            else:
                w.attrs['class'] = 'field__input field__input--plain'
            if isinstance(w, forms.Select):
                w.attrs['class'] += ' field__select'


class StyledModelForm(StyledMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class AccountForm(forms.ModelForm):
    """Used by the Add Account dialog (inputs are rendered by hand)."""

    class Meta:
        model = Account
        fields = ['name', 'domain']

    def clean_name(self):
        return self.cleaned_data['name'].strip()

    def clean_domain(self):
        domain = normalize_domain(self.cleaned_data['domain'])
        if not DOMAIN_RE.match(domain):
            raise forms.ValidationError('Enter a valid domain, e.g. acmebio.com')
        if Account.objects.filter(domain=domain).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('This company is already in the pipeline.')
        return domain


class CompanyForm(StyledMixin, AccountForm):
    class Meta(AccountForm.Meta):
        fields = ['name', 'domain', 'deal_value']
        labels = {'name': 'Company name', 'domain': 'Company domain URL', 'deal_value': 'Deal value'}
        widgets = {'deal_value': forms.TextInput(attrs={'placeholder': '$15K'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class OverviewForm(StyledModelForm):
    class Meta:
        model = Account
        fields = ['what_they_do', 'what_they_service', 'who_they_service']
        labels = {'what_they_do': 'What they do', 'what_they_service': 'What they service', 'who_they_service': 'Who they service'}
        widgets = {f: forms.Textarea(attrs={'rows': 4}) for f in fields}


class ProfileForm(StyledModelForm):
    class Meta:
        model = Account
        fields = ['modality', 'therapeutic_focus', 'trial_phase', 'geography']
        labels = {'modality': 'Modality', 'therapeutic_focus': 'Therapeutic focus', 'trial_phase': 'Trial phase', 'geography': 'Geography'}
        widgets = {f: forms.Textarea(attrs={'rows': 3}) for f in fields}


class IcpForm(StyledModelForm):
    class Meta:
        model = Account
        fields = ['icp', 'icp_source']
        labels = {'icp': 'Their ICP', 'icp_source': 'Source'}
        widgets = {'icp': forms.Textarea(attrs={'rows': 8, 'placeholder': 'One point per line'})}
        help_texts = {'icp': 'One point per line.'}


class DateInput(forms.DateInput):
    input_type = 'date'

    def __init__(self, **kw):
        super().__init__(format='%Y-%m-%d', **kw)


class StageForm(StyledMixin, forms.Form):
    """Done flag and reasoning for each of the 12 steps."""

    def __init__(self, account, *args, **kwargs):
        self.account = account
        super().__init__(*args, **kwargs)
        existing = {r['num']: r for r in account.stage_rows()}
        for num, name in STAGES:
            self.fields[f'done_{num}'] = forms.BooleanField(required=False, initial=existing[num]['done'], label=name)
            self.fields[f'target_{num}'] = forms.DateField(
                required=False, initial=existing[num]['target_date'], label=f'Target date: {name}', widget=DateInput())
            self.fields[f'why_{num}'] = forms.CharField(
                required=False, initial=existing[num]['why'], label=f'Why: {name}',
                widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Evidence for this status'}),
            )
        self._style()
        self.rows = [
            {'num': num, 'name': name, 'weight': STAGE_WEIGHTS[num], 'done': self[f'done_{num}'], 'why': self[f'why_{num}'],
             'target': self[f'target_{num}']}
            for num, name in STAGES
        ]

    def save(self):
        for p in self.account.stage_progress.all():
            p.done = self.cleaned_data[f'done_{p.stage}']
            p.why = self.cleaned_data[f'why_{p.stage}'].strip()
            p.target_date = self.cleaned_data[f'target_{p.stage}']
            p.save(update_fields=['done', 'why', 'target_date'])


class MeetingForm(StyledModelForm):
    class Meta:
        model = MeetingNote
        fields = ['title', 'held_on']
        labels = {'title': 'Meeting', 'held_on': 'Date'}
        widgets = {'title': forms.TextInput(attrs={'placeholder': 'Sep 21 product walkthrough'}), 'held_on': DateInput()}


def meeting_part_form(part):
    label = dict(MEETING_PARTS)[part]

    class MeetingPartForm(StyledModelForm):
        class Meta:
            model = MeetingNote
            fields = [part]
            labels = {part: label}
            widgets = {part: forms.Textarea(attrs={'rows': 8, 'placeholder': 'One point per line'})}
            help_texts = {part: 'One point per line.'}

    return MeetingPartForm


class EventForm(StyledModelForm):
    class Meta:
        model = TimelineEvent
        fields = ['date', 'kind', 'text']
        labels = {'date': 'Date', 'kind': 'Type', 'text': 'What happened'}
        widgets = {'date': DateInput(), 'text': forms.Textarea(attrs={'rows': 3})}


class EmailForm(StyledModelForm):
    class Meta:
        model = SentEmail
        fields = ['sent_on', 'subject', 'recipients', 'body']
        labels = {'sent_on': 'Date sent', 'subject': 'Subject', 'recipients': 'To / cc', 'body': 'Email'}
        widgets = {'sent_on': DateInput(), 'body': forms.Textarea(attrs={'rows': 10})}


class TaskForm(StyledModelForm):
    class Meta:
        model = Task
        fields = ['kind', 'title', 'due_date']
        labels = {'kind': 'Type', 'title': 'What needs to happen', 'due_date': 'Due date'}
        widgets = {'title': forms.TextInput(attrs={'placeholder': 'Send pricing to Suneel'}), 'due_date': DateInput()}


# --- Deal snapshot, short thesis, commercial path: small forms built from a field spec ---
def section_form(spec, intro=''):
    """spec: (field, label, kind, hint). kind is text | area | bullets | date | check."""
    labels = {f: label for f, label, *_ in spec}
    widgets, help_texts = {}, {}
    for f, _, kind, *rest in spec:
        hint = rest[0] if rest else ''
        if kind == 'area':
            widgets[f] = forms.Textarea(attrs={'rows': 4, 'placeholder': hint})
        elif kind == 'bullets':
            widgets[f] = forms.Textarea(attrs={'rows': 5, 'placeholder': 'One point per line'})
            help_texts[f] = hint or 'One point per line.'
        elif kind == 'date':
            widgets[f] = DateInput()
        elif kind == 'text':
            widgets[f] = forms.TextInput(attrs={'placeholder': hint})
        elif kind == 'check' and hint:
            help_texts[f] = hint
    meta = type('Meta', (), {'model': Account, 'fields': [f for f, *_ in spec],
                             'labels': labels, 'widgets': widgets, 'help_texts': help_texts})
    return type('SectionForm', (StyledModelForm,), {'Meta': meta, 'intro': intro})


SNAPSHOT_FORMS = {
    'people': (section_form([
        ('buyer', 'Buyer: who signs and holds the budget', 'bullets'),
        ('champion', 'Champion', 'bullets'),
        ('users', 'Users: who will be in the product', 'bullets'),
        ('blockers', 'Blockers: who or what can stop it', 'bullets'),
        ('who_cares', 'Who actually cares, and why', 'area', 'The person and the reason they care'),
    ]), 'Who decides, who uses it, who can block it', 'people'),
    'move': (section_form([
        ('must_happen', 'What has to happen for the deal to move', 'bullets'),
        ('biggest_risk', 'Biggest current risk', 'area', 'The main reason this may not happen'),
    ]), 'What has to happen, and the biggest risk', 'move'),
    'next': (section_form([
        ('next_action', 'Exact next action', 'text', 'Send Andrea the rerun mAb workspace'),
        ('next_action_owner', 'Owner', 'text', 'Siddharth'),
        ('next_action_date', 'Date', 'date'),
    ]), 'Next action', 'next'),
    'usage': (section_form([
        ('usage_tried', 'At least 1 user tried the product', 'check'),
        ('usage_value', 'At least 1 user reached value (decision makers enriched, email written, or copilot used)', 'check'),
        ('usage_onboarded', '100% of invited users onboarded', 'check'),
        ('integration_started', 'Integration or expansion started', 'check'),
    ]), 'Usage and path', 'path'),
    'why': (section_form([
        ('why_buy', 'Why would this company buy BioLens? Their biggest problem', 'area'),
        ('pain_now', 'What problem is painful enough right now', 'area'),
    ]), 'Why would they buy?', 'thesis-why'),
    'first': (section_form([
        ('buying_first', 'What are they buying first? The specific workflow, not "the platform"', 'area'),
    ]), 'What are they buying first?', 'thesis-first'),
    'before': (section_form([
        ('before_pay', 'What has to happen before they pay', 'bullets', 'Demo, data quality, usage, security, procurement, integration, internal sponsor. One per line.'),
    ]), 'What has to happen before they pay?', 'thesis-before'),
    'expand': (section_form([
        ('expand_when', 'What would make them expand', 'bullets', 'More users, more credits, another workflow, CRM integration, business unit. One per line.'),
        ('expansion_trigger', 'The expansion trigger in one line', 'text', 'Salesforce integration'),
    ]), 'What would make them expand?', 'thesis-expand'),
    'commercial': (section_form([
        ('trial_note', 'Trial or usage terms', 'text', '14 day trial'),
        ('expected_credits', 'Expected usage', 'text', '500 credits a month'),
        ('pilot_value', 'Pilot value', 'text', '$20K'),
        ('pilot_date', 'Pilot date (leave empty to use the predicted date)', 'date'),
        ('annual_value', 'Annual value', 'text', '$75K'),
        ('annual_date', 'Annual decision date (leave empty to use the predicted date)', 'date'),
    ]), 'Realistic commercial path', 'thesis-path'),
    'whynot': (section_form([
        ('why_not', 'Why might they not buy', 'bullets', 'Existing tools, weak usage, no budget, wrong buyer, internal build, procurement, no urgency. One per line.'),
    ]), 'Why might they not buy?', 'thesis-whynot'),
}


class UsageStageForm(StyledModelForm):
    class Meta:
        model = UsageStage
        fields = ['name', 'window', 'healthy', 'credits', 'moves_on', 'gate']
        labels = {'name': 'Stage', 'window': 'When', 'healthy': 'What healthy usage looks like',
                  'credits': 'Credit use to expect', 'moves_on': 'What justifies moving to the next stage',
                  'gate': 'Where to gate or guide in the product'}
        widgets = {
            'healthy': forms.Textarea(attrs={'rows': 6, 'placeholder': 'One point per line'}),
            'credits': forms.Textarea(attrs={'rows': 2}),
            'moves_on': forms.Textarea(attrs={'rows': 3}),
            'gate': forms.Textarea(attrs={'rows': 6, 'placeholder': 'One point per line'}),
        }
        help_texts = {'healthy': 'One point per line.', 'gate': 'One point per line. Start a line with Guide: or Gate: to label it.'}
