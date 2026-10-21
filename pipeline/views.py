import datetime

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from .forms import (SNAPSHOT_FORMS, AccountForm, CompanyForm, EmailForm, EventForm, IcpForm, MeetingForm, OverviewForm,
                    ProfileForm, StageForm, TaskForm, UsageStageForm, meeting_part_form)
from .models import MEETING_PARTS, Account, MeetingNote, SentEmail, StageProgress, Task, TimelineEvent, UsageStage
from .stages import STAGES

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
    'task': (Task, TaskForm, 'task', 'tasks'),
}


@login_required
@require_http_methods(['GET', 'POST'])
def dashboard(request):
    form = AccountForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        account = form.save()
        return redirect('pipeline:account_detail', pk=account.pk)
    accounts = list(Account.objects.prefetch_related('stage_progress'))
    for a in accounts:
        a.cells = a.gantt_cells()
        a.path = a.path_steps()
        a.path_percent = round(sum(p['fraction'] for p in a.path) / len(a.path) * 100)
        a.next_stage_info = a.next_stage
        sched = a.schedule()
        a.contract_info = sched[11]
    return render(request, 'pipeline/dashboard.html', {
        'accounts': accounts,
        'stages': STAGES,
        'form': form,
        'show_form': request.method == 'POST',
        'nav': 'pipeline',
    })


@login_required
def account_detail(request, pk):
    account = get_object_or_404(Account.objects.prefetch_related('stage_progress'), pk=pk)
    tasks = sorted(account.tasks.all(), key=lambda t: (t.done, t.due_date, t.id))
    today = datetime.date.today()
    open_tasks = [t for t in tasks if not t.done]
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
        'tasks': tasks,
        'open_task_count': len(open_tasks),
        'overdue_count': sum(1 for t in open_tasks if t.due_date < today),
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
    if section == 'stages':
        form = StageForm(account, request.POST or None)
        return _form_response(request, form, 'Stage tracker and score', 'stages')
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
def toggle_task(request, pk, item_id):
    task = get_object_or_404(Task, pk=item_id, account_id=pk)
    task.done = not task.done
    task.save(update_fields=['done'])
    return JsonResponse({'ok': True, 'anchor': 'tasks'})


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
@require_POST
def toggle_stage(request, pk, num):
    row = get_object_or_404(StageProgress, account_id=pk, stage=num)
    row.done = not row.done
    row.save(update_fields=['done'])
    return JsonResponse({'ok': True, 'anchor': 'timeline-strip'})


@login_required
@require_POST
def toggle_flag(request, pk, flag):
    if flag not in FLAGS:
        return JsonResponse({'error': 'unknown flag'}, status=404)
    account = get_object_or_404(Account, pk=pk)
    setattr(account, flag, not getattr(account, flag))
    account.save(update_fields=[flag])
    return JsonResponse({'ok': True, 'anchor': 'path-block'})
