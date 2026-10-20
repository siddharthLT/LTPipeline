import re

from django import forms

from .models import MEETING_PARTS, Account, MeetingNote, SentEmail, Task, TimelineEvent, normalize_domain
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


class StageForm(StyledMixin, forms.Form):
    """Done flag and reasoning for each of the 12 steps."""

    def __init__(self, account, *args, **kwargs):
        self.account = account
        super().__init__(*args, **kwargs)
        existing = {r['num']: r for r in account.stage_rows()}
        for num, name in STAGES:
            self.fields[f'done_{num}'] = forms.BooleanField(required=False, initial=existing[num]['done'], label=name)
            self.fields[f'why_{num}'] = forms.CharField(
                required=False, initial=existing[num]['why'], label=f'Why: {name}',
                widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Evidence for this status'}),
            )
        self._style()
        self.rows = [
            {'num': num, 'name': name, 'weight': STAGE_WEIGHTS[num], 'done': self[f'done_{num}'], 'why': self[f'why_{num}']}
            for num, name in STAGES
        ]

    def save(self):
        for p in self.account.stage_progress.all():
            p.done = self.cleaned_data[f'done_{p.stage}']
            p.why = self.cleaned_data[f'why_{p.stage}'].strip()
            p.save(update_fields=['done', 'why'])


class DateInput(forms.DateInput):
    input_type = 'date'

    def __init__(self, **kw):
        super().__init__(format='%Y-%m-%d', **kw)


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
