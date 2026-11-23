import datetime
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from .forms import (SNAPSHOT_FORMS, AccountForm, ActionForm, CompanyForm, EmailForm, EventForm, IcpForm, MeetingForm, OverviewForm,
                    ProfileForm, StageEditForm, UsageStageForm, meeting_part_form)
from .models import MEETING_PARTS, SEGMENTS, Account, MeetingNote, SentEmail, StageProgress, Task, TimelineEvent, UsageStage
from . import exports
from .forecast import build as build_forecast, advisor_names
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


SIGNAL_FIELDS = ('buyer', 'champion', 'users', 'blockers', 'must_happen', 'biggest_risk', 'next_action', 'pain_now',
                 'why_buy', 'before_pay', 'expand_when', 'expansion_trigger')


def _signal_text(account):
    """Everything we have written about an account, scanned for what it has asked for (CRM sync, security, hosting)."""
    parts = [getattr(account, f) for f in SIGNAL_FIELDS]
    parts += [e.text for e in account.events.all()] + [t.title for t in account.tasks.all()]
    return ' '.join(parts)


@login_required
@require_http_methods(['GET', 'POST'])
def dashboard(request):
    form = AccountForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        account = form.save()
        return redirect('pipeline:account_detail', pk=account.pk)
    accounts = list(Account.objects.prefetch_related('stage_progress', 'tasks', 'events'))
    accounts.sort(key=lambda a: (-a.score, a.name.lower()))
    for a in accounts:
        a.cells = a.gantt_cells()
        a.path = a.path_steps()
        a.path_percent = round(sum(p['fraction'] for p in a.path) / len(a.path) * 100)
        a.next_stage_info = a.next_stage
        sched = a.schedule()
        a.contract_info = sched[11]
        a.signal_text = _signal_text(a)
        a.key_connections = [n for n in advisor_names(a.advisors) if n in ('Mak', 'Abhishek')]
    forecast = build_forecast(accounts)
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
        'name': a.name, 'domain': a.domain, 'advisors': a.advisors, 'segment': a.get_segment_display() if a.segment else '',
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


def _export_queryset():
    return Account.objects.prefetch_related('stage_progress', 'tasks', 'events', 'emails', 'meetings')


@login_required
def download_json(request, pk):
    account = get_object_or_404(_export_queryset(), pk=pk)
    response = HttpResponse(exports.json_bytes(account), content_type='application/json; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{exports.filename(account, "json")}"'
    return response


@login_required
def download_pdf(request, pk):
    account = get_object_or_404(_export_queryset(), pk=pk)
    response = HttpResponse(exports.pdf_bytes(account), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{exports.filename(account, "pdf")}"'
    return response


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
def actions(request):
    show = request.GET.get('show', 'open')
    if show not in ('open', 'done', 'all'):
        show = 'open'
    picked = {int(c) for c in request.GET.getlist('company') if c.isdigit()}
    low = _number(request.GET.get('min'), 0, 0, 100)
    high = _number(request.GET.get('max'), 100, 0, 100)
    tasks = Task.objects.select_related('account').prefetch_related('account__stage_progress')
    if picked:
        tasks = tasks.filter(account_id__in=picked)
    tasks = [t for t in tasks if low <= t.account.score <= high]
    counts = {'open': sum(not t.done for t in tasks), 'done': sum(t.done for t in tasks)}
    counts['all'] = counts['open'] + counts['done']
    if show != 'all':
        tasks = [t for t in tasks if t.done == (show == 'done')]
    accounts = sorted(Account.objects.prefetch_related('stage_progress'), key=lambda a: a.name.lower())
    query = request.GET.copy()
    query.pop('show', None)
    clients = [t for t in tasks if t.account.score >= 100]  # active clients: every deal stage reached
    return render(request, 'pipeline/actions.html', {
        'pipeline_tasks': [t for t in tasks if t.account.score < 100], 'client_tasks': clients, 'show': show,
        'counts': counts, 'today': datetime.date.today(), 'nav': 'actions', 'accounts': accounts, 'picked': picked,
        'low': low, 'high': high, 'filtered': bool(picked) or low > 0 or high < 100, 'query': query.urlencode()})


def _lines(text):
    """One entry per non-empty line, bullet marks removed."""
    return [ln.strip().lstrip('-•* ').strip() for ln in (text or '').splitlines() if ln.strip()]


def _ago(days):
    return 'today' if days <= 0 else 'yesterday' if days == 1 else f'{days} days ago'


@login_required
def hand_raisers(request):
    """Deal-movement deck for the accounts picked on the Pipeline page (?ids=1,2,3). Uses only stored data."""
    today = datetime.date.today()
    ids = [int(i) for i in request.GET.get('ids', '').split(',') if i.strip().isdigit()]
    by_id = {a.pk: a for a in Account.objects.filter(pk__in=ids).prefetch_related('stage_progress', 'tasks', 'events')}
    accounts = [by_id[i] for i in dict.fromkeys(ids) if i in by_id]
    # Overview rows per slide: at most 6, split evenly (10 accounts -> 5 + 5)
    pages = -(-len(accounts) // 6) if len(accounts) > 1 else 0
    per = -(-len(accounts) // pages) if pages else 0
    overview = [accounts[i:i + per] for i in range(0, len(accounts), per)] if pages else []
    for n, a in enumerate(accounts):
        a.slide_no = pages + 2 * n + 1
        furthest = a.furthest_stage
        a.rows = a.stage_rows()
        for r in a.rows:
            r['state'] = 'done' if r['done'] else 'part' if r['met'] else 'gap' if r['num'] < furthest else 'open'
            r['current'] = furthest > 0 and r['num'] == furthest
        a.next_row = a.rows[furthest] if furthest < len(a.rows) else None
        a.feed = sorted(a.events.all(), key=lambda e: (e.date, e.id), reverse=True)[:6]
        last = a.feed[0] if a.feed else None
        a.last_touch = {'ago': _ago((today - last.date).days), 'date': last.date, 'kind': last.get_kind_display()} if last else None
        a.deck_actions = sorted(a.open_actions(), key=lambda t: (t.due_date is None, t.due_date or datetime.date.max, t.id))
        a.overdue = sum(1 for t in a.deck_actions if t.due_date and t.due_date < today)
        a.next_dated = next((t for t in a.deck_actions if t.due_date), None)
        a.blocker_list, a.must_list = _lines(a.blockers), _lines(a.must_happen)
        a.icp_list = _lines(a.icp)
    return render(request, 'pipeline/hand_raisers.html', {'accounts': accounts, 'today': today, 'overview': overview})


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
    ('Company', [('segment', 'Segment'), ('domain', 'Domain'), ('deal_value', 'Deal value'),
                ('sales_marketing_team', 'Sales and marketing team')]),
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
    sort = request.GET.get('sort', 'most')
    if sort == 'name':
        rows.sort(key=lambda r: r['account'].name.lower())
    elif sort == 'least':
        rows.sort(key=lambda r: (r['percent'], r['account'].name.lower()))
    else:
        sort = 'most'
        rows.sort(key=lambda r: (-r['percent'], r['account'].name.lower()))
    n = len(rows) or 1
    footer = [round(totals[attr] / n * 100) for attr, _ in columns]
    return render(request, 'pipeline/health_check.html', {
        'groups': [(name, len(fields)) for name, fields in HEALTH_GROUPS],
        'columns': [label for _, label in columns],
        'rows': rows, 'footer': footer, 'sort': sort,
        'overall': round(sum(r['filled'] for r in rows) / (n * len(columns)) * 100),
        'field_count': len(columns), 'account_count': len(rows), 'nav': 'health',
    })


@login_required
def usage(request):
    from . import posthog
    try:
        days = int(request.GET.get('days', 30))
    except ValueError:
        days = 30
    days = days if days in (7, 14, 30, 90) else 30
    tab = request.GET.get('tab', 'overview')
    tab = tab if tab in ('overview', 'funnel', 'accounts', 'recordings', 'users', 'daily', 'unmatched') else 'overview'
    if request.GET.get('refresh'):
        from django.core.cache import cache
        cache.delete('posthog-usage-%d' % days)
        cache.delete('posthog-recordings-%d' % days)
    accounts = list(Account.objects.prefetch_related('stage_progress'))
    ctx = {'nav': 'usage', 'days': days, 'tab': tab, 'actions': list(zip(posthog.SHORT, [l for _, l in posthog.ACTIONS])),
           'windows': (7, 14, 30, 90)}
    try:
        rows, unmatched, daily, totals = posthog.join(accounts, days)
        by_day = {}
        for d in daily:
            by_day.setdefault(d['day'], []).append(d)
        using = {m['account'].pk for m in rows}
        ctx.update(rows=rows, unmatched=unmatched, days_list=sorted(by_day.items(), reverse=True), totals=totals,
                   users=[dict(u, account=m['account']) for m in rows for u in m['users']],
                   tracked=len(accounts), with_usage=len(rows),
                   quiet=sorted((a for a in accounts if a.pk not in using), key=lambda a: (-a.furthest_stage, a.name)))
        if tab in ('overview', 'accounts'):
            ctx['shape'] = posthog.shape(rows, daily, days)
        if tab == 'recordings':
            ctx.update(_recordings_context(accounts, days))
        if tab == 'funnel':
            from . import funnel
            ctx.update(funnel=funnel.build(accounts, days))
    except posthog.NotConfigured as e:
        ctx['error'] = str(e)
    except Exception as e:  # network or PostHog errors should not break the page
        ctx['error'] = 'PostHog did not answer: %s' % e
    return render(request, 'pipeline/usage.html', ctx)


def _recordings_context(accounts, days):
    """Recordings grouped into account playlists, with length buckets for the filter chips."""
    from . import posthog
    by_domain = posthog.by_domain_of(accounts)
    recs = posthog.recordings(days)
    lists = {}
    for r in recs:
        a = posthog.match_account(r['email'], by_domain)
        r['account'] = a
        r['key'] = str(a.pk) if a else 'x'
        r['brand'] = a.name if a else posthog.domain_of(r['email'])
        p = lists.setdefault(r['key'], {'key': r['key'], 'name': a.name if a else 'Not in tracker', 'account': a,
                                        'n': 0, 'active': 0, 'dur': 0})
        p['n'] += 1; p['active'] += r['active']; p['dur'] += r['dur']
    playlists = sorted(lists.values(), key=lambda p: (p['key'] == 'x', -p['n']))
    buckets = [{'key': k, 'label': label, 'n': sum(1 for r in recs if r['bucket'] == k)} for k, label, _ in posthog.BUCKETS]
    return {'recs': recs, 'playlists': playlists, 'buckets': buckets, 'rec_active': sum(r['active'] for r in recs)}


MAPPED_PAGE = 50


@login_required
def mapped_suggest(request):
    """Up to eight mapped companies matching what is being typed, for the search dropdown."""
    from django.db.models import Case, IntegerField, Q, Value, When
    from .models import MappedCompany
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    qs = MappedCompany.objects.filter(Q(name__icontains=q) | Q(domain__icontains=q) | Q(city__icontains=q))
    for key, field in (('region', 'world_region'), ('country', 'country')):
        if request.GET.get(key):
            qs = qs.filter(**{field: request.GET[key]})
    if request.GET.get('country') == 'United States' and request.GET.getlist('state'):
        qs = qs.filter(state__in=request.GET.getlist('state'))
    if request.GET.getlist('segment'):
        qs = qs.filter(segment__in=request.GET.getlist('segment'))
    qs = qs.annotate(rank=Case(When(name__istartswith=q, then=Value(0)), When(name__icontains=q, then=Value(1)), default=Value(2),
                               output_field=IntegerField())).order_by('rank', 'name')[:8]
    return JsonResponse({'results': [{'name': m.name, 'domain': m.domain, 'segment': m.segment, 'logo': m.logo_url,
                                      'place': ', '.join(x for x in (m.city, m.state if m.country == 'United States' else m.country) if x)}
                                     for m in qs]})


@login_required
def mapped_universe(request):
    """Every mapped company, in the pipeline or not, as a paginated list or a world map. Filters apply to both."""
    from django.core.paginator import Paginator
    from django.db.models import Count, Q
    from .models import WORLD_REGIONS, MappedCompany
    g = request.GET
    q = g.get('q', '').strip()
    segs = [x for x in g.getlist('segment') if x]
    view = 'map' if g.get('view') == 'map' else 'list'
    region = g.get('region', '')
    country = g.get('country', '')
    states = [s for s in g.getlist('state') if s] if country == 'United States' else []  # states only apply once United States is chosen
    logo = g.get('logo', '')
    located = g.get('located', '')
    focus = g.get('focus', '')
    pipe = g.get('pipe', '') if g.get('pipe') in ('in', 'out') else ''
    in_pipeline = dict(Account.objects.values_list('domain', 'pk'))  # a mapped company is in the pipeline when an account has its domain
    base = MappedCompany.objects.all()
    qs = base
    if pipe == 'in':
        qs = qs.filter(domain__in=in_pipeline)
    elif pipe == 'out':
        qs = qs.exclude(domain__in=in_pipeline)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(domain__icontains=q) | Q(city__icontains=q) | Q(address__icontains=q) | Q(product_category__icontains=q))
    if segs:
        qs = qs.filter(segment__in=segs)
    if region:
        qs = qs.filter(world_region=region)
    if country:
        qs = qs.filter(country=country)
    if states:
        qs = qs.filter(state__in=states)
    if logo == 'no':
        qs = qs.filter(logo_url='')
    if located == 'no':
        qs = qs.filter(latitude__isnull=True)

    def link(**over):
        params = {'q': q, 'segment': segs, 'region': region, 'country': country, 'state': states, 'logo': logo,
                  'located': located, 'pipe': pipe, 'view': 'map' if view == 'map' else ''}
        params.update(over)
        return urlencode({k: v for k, v in params.items() if v}, doseq=True)

    seg_counts = dict(base.values_list('segment').annotate(n=Count('id')).order_by())
    segments = [{'name': name, 'n': n, 'on': name in segs,
                 'qs': link(segment=[x for x in segs if x != name] if name in segs else segs + [name], page='')}
                for name, n in sorted(seg_counts.items(), key=lambda kv: -kv[1])]
    region_counts = dict(base.values_list('world_region').annotate(n=Count('id')).order_by())
    regions = [{'name': name, 'n': region_counts.get(name, 0), 'on': name == region, 'qs': link(region='' if name == region else name, page='', focus='')}
               for name in WORLD_REGIONS if region_counts.get(name)]
    unlocated = base.filter(latitude__isnull=True).count()
    ctx = {
        'nav': 'mapped', 'view': view, 'total': base.count(), 'shown': qs.count(),
        'q': q, 'segments': segments, 'regions': regions, 'region': region, 'country': country, 'states': states, 'logo': logo,
        'located': located, 'pipe': pipe, 'in_pipe': base.filter(domain__in=in_pipeline).count(), 'unlocated': unlocated, 'unlocated_qs': link(located='' if located == 'no' else 'no', page=''),
        'countries': list(base.exclude(country='').order_by('country').values_list('country', flat=True).distinct()),
        'state_chips': [{'name': s, 'on': s in states, 'qs': link(state=[x for x in states if x != s] if s in states else states + [s], page='', focus='')}
                        for s in base.filter(country='United States').exclude(state='').order_by('state').values_list('state', flat=True).distinct()],
        'segs': segs, 'clear': any([q, segs, region, country, states, logo, located, pipe]), 'form': AccountForm(),
        'list_qs': link(view=''), 'map_qs': link(view='map'),
        'page_size': MAPPED_PAGE,
    }
    if view == 'map':
        points = list(qs.exclude(latitude__isnull=True).values(
            'id', 'name', 'domain', 'url', 'segment', 'city', 'state', 'country', 'address', 'latitude', 'longitude', 'geo_source', 'logo_url'))
        ctx.update(points=[{'id': p['id'], 'n': p['name'], 'd': p['domain'], 'u': p['url'], 's': p['segment'], 'c': p['city'], 'st': p['state'],
                            'co': p['country'], 'a': p['address'], 'la': round(p['latitude'], 5), 'ln': round(p['longitude'], 5),
                            'g': p['geo_source'], 'l': p['logo_url'],
                            'pp': reverse('pipeline:account_detail', args=[in_pipeline[p['domain']]]) if p['domain'] in in_pipeline else ''}
                           for p in points],
                   mapped=len(points), not_mapped=ctx['shown'] - len(points), focus=focus)
    else:
        page = Paginator(qs.order_by('name'), MAPPED_PAGE).get_page(g.get('page'))
        for c in page:
            c.account_id = in_pipeline.get(c.domain)
        ctx.update(page=page, prev_qs=link(page=page.previous_page_number()) if page.has_previous() else '',
                   next_qs=link(page=page.next_page_number()) if page.has_next() else '')
    return render(request, 'pipeline/mapped_universe.html', ctx)
