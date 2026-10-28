import re

from django import forms

from .models import MEETING_PARTS, Account, MeetingNote, SentEmail, Task, TimelineEvent, UsageStage, normalize_domain
from .stages import CRITERIA

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
        fields = ['name', 'domain', 'segment', 'deal_value', 'sales_marketing_team', 'advisors']
        labels = {'segment': 'Segment', 'name': 'Company name', 'domain': 'Company domain URL', 'deal_value': 'Deal value',
                  'sales_marketing_team': 'Sales and marketing team size', 'advisors': 'Advisors who connect us'}
        widgets = {'deal_value': forms.TextInput(attrs={'placeholder': '$15K'}),
                   'advisors': forms.TextInput(attrs={'placeholder': 'Mak, PK'})}

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


class StageEditForm(StyledMixin, forms.Form):
    """One step: tick the criteria that are met. The step is done when every criterion is met."""

    def __init__(self, account, num, *args, **kwargs):
        self.progress = account.stage_progress.get(stage=num)
        super().__init__(*args, **kwargs)
        met = set(self.progress.criteria)
        for key, label in CRITERIA[num]:
            self.fields[f'c_{key}'] = forms.BooleanField(required=False, initial=key in met, label=label)
        self.fields['why'] = forms.CharField(
            required=False, initial=self.progress.why, label='Evidence',
            widget=forms.Textarea(attrs={'rows': 4, 'placeholder': 'What shows these criteria are met, or what is missing'}))
        self.fields['target_date'] = forms.DateField(
            required=False, initial=self.progress.target_date, label='Target date (optional)', widget=DateInput())
        self.num = num
        self.intro = f'Done when all {len(CRITERIA[num])} criteria are met. A target date replaces the predicted date and moves the steps after it.'
        self._style()

    def save(self):
        p = self.progress
        p.criteria = [k for k, _ in CRITERIA[self.num] if self.cleaned_data[f'c_{k}']]
        p.done = len(p.criteria) == len(CRITERIA[self.num])
        p.why = self.cleaned_data['why'].strip()
        p.target_date = self.cleaned_data['target_date']
        p.save(update_fields=['criteria', 'done', 'why', 'target_date'])
        return p


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


class ActionForm(StyledModelForm):
    class Meta:
        model = Task
        fields = ['title', 'owner', 'due_date']
        labels = {'title': 'What needs to happen', 'owner': 'Owner', 'due_date': 'Date'}
        widgets = {'title': forms.TextInput(attrs={'placeholder': 'Send Andrea the rerun mAb workspace'}),
                   'owner': forms.TextInput(attrs={'placeholder': 'Siddharth'}), 'due_date': DateInput()}


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
