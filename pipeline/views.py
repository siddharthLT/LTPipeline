import datetime

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from .forms import (SNAPSHOT_FORMS, AccountForm, ActionForm, CompanyForm, EmailForm, EventForm, IcpForm, MeetingForm, OverviewForm,
                    ProfileForm, StageEditForm, UsageStageForm, meeting_part_form)
from .models import MEETING_PARTS, SEGMENTS, Account, MeetingNote, SentEmail, StageProgress, Task, TimelineEvent, UsageStage
from .forecast import DEFAULT_CONVERSION, DEFAULT_CYCLE_MONTHS
from .forecast import build as build_forecast
from .stages import CRITERIA, PATH, STAGE_DAYS, STAGE_NAMES, STAGE_WEIGHTS, STAGES, USAGE_CHECKS

SECTIONS = {
    'company': (CompanyForm, 'Company', 'company'),
    'overview': (OverviewForm, 'What they do, service, and who they service', 'overview'),
    'profile': (ProfileForm, 'Modality, focus area, phase, geography', 'profile'),
    'icp': (IcpForm, 'Their ICP', 'icp'),
}

# kind -> (model, form, label, anchor)
ITEMS = {
    'meeting': (MeetingNote, MeetingForm, 'meeting', 'meetings'),
    'event': (TimelineEvent, EventForm, 'timeline entry', 'timeline'),
    'email': (SentEmail, EmailForm, 'sent email', 'timeline'),
    'action': (Task, ActionForm, 'next action', 'next-actions'),
}


def _number(raw, default, low, high):
    try:
        return min(max(int(raw), low), high)
    except (TypeError, ValueError):
        return default


@login_required
@require_http_methods(['GET', 'POST'])
def dashboard(request):
    form = AccountForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        account = form.save()
        return redirect('pipeline:account_detail', pk=account.pk)
    accounts = list(Account.objects.prefetch_related('stage_progress', 'tasks'))
    accounts.sort(key=lambda a: (-a.score, a.name.lower()))
    cycle = _number(request.GET.get('cycle'), DEFAULT_CYCLE_MONTHS, 1, 24)
    conv = _number(request.GET.get('conv'), round(DEFAULT_CONVERSION * 100), 1, 100)
    for a in accounts:
        a.cells = a.gantt_cells()
        a.path = a.path_steps()
        a.path_percent = round(sum(p['fraction'] for p in a.path) / len(a.path) * 100)
        a.next_stage_info = a.next_stage
        sched = a.schedule()
        a.contract_info = sched[11]
    forecast = build_forecast(accounts, cycle_months=cycle, conversion=conv / 100)
    return render(request, 'pipeline/dashboard.html', {
        'forecast': forecast,
        'accounts': accounts,
        'stages': STAGES,
        'segments': SEGMENTS,
        'form': form,
        'show_form': request.method == 'POST',
        'nav': 'pipeline',
    })


@login_required
def search_index(request):
    """Accounts for the Cmd/Ctrl+K palette."""
    accounts = Account.objects.prefetch_related('stage_progress')
    rows = [{
        'name': a.name, 'domain': a.domain, 'segment': a.get_segment_display() if a.segment else '',
        'score': a.score, 'stage': a.furthest_stage_name,
        'url': reverse('pipeline:account_detail', args=[a.pk]),
    } for a in accounts]
    rows.sort(key=lambda r: (-r['score'], r['name'].lower()))
    return JsonResponse({'accounts': rows})


@login_required
def account_detail(request, pk):
    account = get_object_or_404(Account.objects.prefetch_related('stage_progress', 'tasks'), pk=pk)
    today = datetime.date.today()
    schedule = account.schedule()
    path = account.path_steps()
    return render(request, 'pipeline/account_detail.html', {
        'account': account,
        'schedule': schedule,
        'next_stage': account.next_stage,
        'contract': schedule[11],
        'path': path,
        'path_pct': round(sum(p['fraction'] for p in path) / len(path) * 100),
        'commercial': account.commercial_nodes(),
        'stage_rows': account.stage_rows(),
        'meetings': account.meetings.all(),
        'events': account.events.all(),
        'emails': account.emails.all(),
        'today': today,
        'nav': 'pipeline',
        'circumference': 439.82,
        'score_dash': round(account.score / 100 * 439.82, 1),
    })


def _form_response(request, form, title, saved_anchor, delete_url=None, submit_label='Save'):
    """GET -> form fragment; valid POST -> JSON ok; invalid POST -> fragment with errors (400)."""
    if request.method == 'POST' and form.is_valid():
        form.save()
        return JsonResponse({'ok': True, 'anchor': saved_anchor})
    return render(request, 'pipeline/_form.html', {
        'form': form, 'title': title, 'action': request.path,
        'delete_url': delete_url, 'submit_label': submit_label,
    }, status=400 if request.method == 'POST' else 200)


@login_required
@require_http_methods(['GET', 'POST'])
def edit_section(request, pk, section):
    account = get_object_or_404(Account, pk=pk)
    if section in SNAPSHOT_FORMS:
        form_class, title, anchor = SNAPSHOT_FORMS[section]
        return _form_response(request, form_class(request.POST or None, instance=account), title, anchor)
    if section not in SECTIONS:
        return JsonResponse({'error': 'unknown section'}, status=404)
    form_class, title, anchor = SECTIONS[section]
    form = form_class(request.POST or None, instance=account)
    return _form_response(request, form, title, anchor)


@login_required
@require_http_methods(['GET', 'POST'])
def edit_item(request, pk, kind, item_id=None):
    account = get_object_or_404(Account, pk=pk)
    if kind not in ITEMS:
        return JsonResponse({'error': 'unknown item'}, status=404)
    model, form_class, label, anchor = ITEMS[kind]
    instance = get_object_or_404(model, pk=item_id, account=account) if item_id else model(account=account)
    form = form_class(request.POST or None, instance=instance)
    delete_url = None
    if item_id:
        delete_url = reverse('pipeline:item_delete', args=[pk, kind, item_id])
    title = f'Edit {label}' if item_id else f'Add {label}'
    return _form_response(request, form, title, anchor, delete_url, 'Save' if item_id else 'Add')


@login_required
@require_http_methods(['GET', 'POST'])
def edit_meeting_part(request, pk, meeting_id, part):
    meeting = get_object_or_404(MeetingNote, pk=meeting_id, account_id=pk)
    labels = dict(MEETING_PARTS)
    if part not in labels:
        return JsonResponse({'error': 'unknown part'}, status=404)
    form = meeting_part_form(part)(request.POST or None, instance=meeting)
    return _form_response(request, form, labels[part], f'meeting-{meeting.pk}')


@login_required
@require_POST
def delete_item(request, pk, kind, item_id):
    if kind not in ITEMS:
        return JsonResponse({'error': 'unknown item'}, status=404)
    model, _, _, anchor = ITEMS[kind]
    get_object_or_404(model, pk=item_id, account_id=pk).delete()
    return JsonResponse({'ok': True, 'anchor': anchor})


@login_required
@require_POST
def toggle_action(request, pk, item_id):
    task = get_object_or_404(Task, pk=item_id, account_id=pk)
    task.done = not task.done
    task.save(update_fields=['done'])
    return JsonResponse({'ok': True, 'anchor': 'next-actions'})


@login_required
def playbook(request):
    return render(request, 'pipeline/playbook.html', {'stages': UsageStage.objects.all(), 'nav': 'playbook'})


@login_required
@require_http_methods(['GET', 'POST'])
def edit_usage_stage(request, pk):
    stage = get_object_or_404(UsageStage, pk=pk)
    form = UsageStageForm(request.POST or None, instance=stage)
    return _form_response(request, form, f'Edit: {stage.name}', f'usage-{stage.pk}')


FLAGS = ('usage_tried', 'usage_value', 'usage_onboarded', 'integration_started')


@login_required
@require_http_methods(['GET', 'POST'])
def edit_stage(request, pk, num):
    account = get_object_or_404(Account, pk=pk)
    if num not in STAGE_NAMES:
        return JsonResponse({'error': 'unknown step'}, status=404)
    form = StageEditForm(account, num, request.POST or None)
    return _form_response(request, form, f'Step {num}: {STAGE_NAMES[num]}', 'timeline-strip')


@login_required
@require_POST
def toggle_flag(request, pk, flag):
    if flag not in FLAGS:
        return JsonResponse({'error': 'unknown flag'}, status=404)
    account = get_object_or_404(Account, pk=pk)
    setattr(account, flag, not getattr(account, flag))
    account.save(update_fields=[flag])
    return JsonResponse({'ok': True, 'anchor': 'path-block'})


@login_required
def rules(request):
    stages = [{'num': n, 'name': name, 'weight': STAGE_WEIGHTS[n], 'days': STAGE_DAYS[n],
               'criteria': [label for _, label in CRITERIA[n]]} for n, name in STAGES]
    return render(request, 'pipeline/rules.html', {
        'stages': stages, 'path': PATH, 'usage_checks': [label for _, label in USAGE_CHECKS],
        'total_days': sum(STAGE_DAYS.values()), 'nav': 'rules',
    })


# Health check: every Account field, grouped like the account page. (attr, column label)
HEALTH_GROUPS = [
    ('Company', [('segment', 'Segment'), ('domain', 'Domain'), ('deal_value', 'Deal value')]),
    ('What they do', [('what_they_do', 'What they do'), ('what_they_service', 'What they service'),
                      ('who_they_service', 'Who they service')]),
    ('Profile', [('modality', 'Modality'), ('therapeutic_focus', 'Therapeutic focus'), ('trial_phase', 'Trial phase'),
                 ('geography', 'Geography')]),
    ('ICP', [('icp', 'ICP'), ('icp_source', 'ICP source')]),
    ('Deal snapshot', [('buyer', 'Buyer'), ('champion', 'Champion'), ('users', 'Users'), ('blockers', 'Blockers'),
                       ('must_happen', 'Must happen'), ('biggest_risk', 'Biggest risk'), ('next_action', 'Next action'),
                       ('next_action_owner', 'Action owner'), ('next_action_date', 'Action date')]),
    ('Usage checks', [('usage_tried', 'Tried'), ('usage_value', 'Reached value'), ('usage_onboarded', 'Onboarded'),
                      ('integration_started', 'Integration started')]),
    ('Buying thesis', [('why_buy', 'Why buy'), ('pain_now', 'Pain now'), ('who_cares', 'Who cares'),
                       ('buying_first', 'Buying first'), ('before_pay', 'Before pay'), ('expand_when', 'Expand when'),
                       ('why_not', 'Why not')]),
    ('Pilot and annual', [('trial_note', 'Trial note'), ('expected_credits', 'Expected credits'),
                          ('pilot_value', 'Pilot value'), ('pilot_date', 'Pilot date'), ('annual_value', 'Annual value'),
                          ('annual_date', 'Annual date'), ('expansion_trigger', 'Expansion trigger')]),
    ('Activity', [('_events', 'Timeline'), ('_emails', 'Sent emails'), ('_meetings', 'Meeting notes'),
                  ('_open_tasks', 'Open action')]),
]


@login_required
def health_check(request):
    accounts = list(Account.objects.prefetch_related('tasks', 'events', 'emails', 'meetings'))
    columns = [(attr, label) for _, fields in HEALTH_GROUPS for attr, label in fields]
    totals = dict.fromkeys((c[0] for c in columns), 0)
    rows = []
    for a in accounts:
        extra = {'_events': bool(a.events.all()), '_emails': bool(a.emails.all()), '_meetings': bool(a.meetings.all()),
                 '_open_tasks': any(not t.done for t in a.tasks.all())}
        cells = []
        for attr, _ in columns:
            value = extra[attr] if attr in extra else getattr(a, attr)
            filled = bool(value.strip()) if isinstance(value, str) else bool(value)
            totals[attr] += filled
            cells.append(filled)
        done = sum(cells)
        rows.append({'account': a, 'cells': cells, 'filled': done, 'percent': round(done / len(cells) * 100)})
    sort = request.GET.get('sort', 'least')
    if sort == 'name':
        rows.sort(key=lambda r: r['account'].name.lower())
    elif sort == 'most':
        rows.sort(key=lambda r: (-r['percent'], r['account'].name.lower()))
    else:
        sort = 'least'
        rows.sort(key=lambda r: (r['percent'], r['account'].name.lower()))
    n = len(rows) or 1
    footer = [round(totals[attr] / n * 100) for attr, _ in columns]
    return render(request, 'pipeline/health_check.html', {
        'groups': [(name, len(fields)) for name, fields in HEALTH_GROUPS],
        'columns': [label for _, label in columns],
        'rows': rows, 'footer': footer, 'sort': sort,
        'overall': round(sum(r['filled'] for r in rows) / (n * len(columns)) * 100),
        'field_count': len(columns), 'account_count': len(rows), 'nav': 'health',
    })
