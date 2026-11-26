"""Outreach tracker: campaigns, each with a brief, ordered steps and an audience ticked off step by step."""
import json
import re

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import Campaign, CampaignPerson, CampaignStep, StepDone


def _back(campaign):
    return redirect(reverse('pipeline:outreach_detail', args=[campaign.pk]))


def parse_people(text):
    """One person per line: Name | Title | Company | anything else. An @ is read as the email, linkedin.com as the profile, a number as the phone."""
    out = []
    for line in text.splitlines():
        parts = [p.strip() for p in re.split(r'\t|\|', line) if p.strip()]
        if not parts:
            continue
        p = {'name': '', 'title': '', 'company': '', 'email': '', 'phone': '', 'linkedin_url': ''}
        plain = []
        for tok in parts:
            if 'linkedin.com' in tok.lower():
                p['linkedin_url'] = tok if tok.startswith('http') else 'https://' + tok
            elif '@' in tok and ' ' not in tok:
                p['email'] = tok
            elif re.fullmatch(r'[+\d][\d\s().-]{6,}', tok):
                p['phone'] = tok
            else:
                plain.append(tok)
        for key, tok in zip(('name', 'title', 'company'), plain):
            p[key] = tok
        if p['name']:
            out.append(p)
    return out


@login_required
def outreach_list(request):
    tag = request.GET.get('tag', '')
    qs = Campaign.objects.annotate(n_people=Count('people', distinct=True), n_steps=Count('steps', distinct=True))
    cards = []
    for c in qs:
        ticks = StepDone.objects.filter(person__campaign=c).count()
        total = c.n_people * c.n_steps
        cards.append({'c': c, 'ticks': ticks, 'total': total, 'pct': round(ticks / total * 100) if total else 0})
    counts = {k: sum(1 for x in cards if x['c'].tag == k) for k, _ in Campaign.TAGS}
    if tag in counts:
        cards = [x for x in cards if x['c'].tag == tag]
    return render(request, 'pipeline/outreach_list.html', {
        'nav': 'outreach', 'cards': cards, 'tag': tag if tag in counts else '', 'tags': [(k, l, counts[k]) for k, l in Campaign.TAGS],
        'all_count': sum(counts.values()), 'choices': Campaign.TAGS})


@login_required
@require_POST
def outreach_create(request):
    name = request.POST.get('name', '').strip()
    if not name:
        return redirect('pipeline:outreach')
    tag = request.POST.get('tag') if request.POST.get('tag') in dict(Campaign.TAGS) else 'gtm'
    c = Campaign.objects.create(name=name, tag=tag, brief=request.POST.get('brief', '').strip())
    return _back(c)


@login_required
def outreach_detail(request, pk):
    c = get_object_or_404(Campaign, pk=pk)
    steps = list(c.steps.all())
    people = list(c.people.all())
    done = {(d.person_id, d.step_id) for d in StepDone.objects.filter(person__campaign=c)}
    for s in steps:
        s.n_done = sum(1 for p in people if (p.pk, s.pk) in done)
    for p in people:
        p.cells = [{'step': s, 'on': (p.pk, s.pk) in done} for s in steps]
        p.n_done = sum(1 for x in p.cells if x['on'])
    ticks = sum(s.n_done for s in steps)
    total = len(people) * len(steps)
    return render(request, 'pipeline/outreach_detail.html', {
        'nav': 'outreach', 'c': c, 'steps': steps, 'people': people, 'ticks': ticks, 'total': total,
        'pct': round(ticks / total * 100) if total else 0, 'kinds': CampaignStep.KINDS, 'tags': Campaign.TAGS})


@login_required
@require_POST
def outreach_edit(request, pk):
    c = get_object_or_404(Campaign, pk=pk)
    c.name = request.POST.get('name', '').strip() or c.name
    if request.POST.get('tag') in dict(Campaign.TAGS):
        c.tag = request.POST['tag']
    c.brief = request.POST.get('brief', '').strip()
    c.save()
    return _back(c)


@login_required
@require_POST
def outreach_delete(request, pk):
    get_object_or_404(Campaign, pk=pk).delete()
    return redirect('pipeline:outreach')


@login_required
@require_POST
def step_save(request, pk):
    c = get_object_or_404(Campaign, pk=pk)
    step = get_object_or_404(CampaignStep, pk=request.POST['step'], campaign=c) if request.POST.get('step') else None
    kind = request.POST.get('kind')
    if kind not in dict(CampaignStep.KINDS):
        return _back(c)
    try:
        wait = max(0, int(request.POST.get('wait_days') or 0))
    except ValueError:
        wait = 0
    if not step:
        last = c.steps.order_by('-position').first()
        step = CampaignStep(campaign=c, position=(last.position + 1) if last else 1)
    step.kind, step.wait_days = kind, wait
    step.subject = request.POST.get('subject', '').strip() if kind == 'email' else ''
    step.note = request.POST.get('note', '').strip()
    step.save()
    return _back(c)


@login_required
@require_POST
def step_delete(request, pk, step_id):
    c = get_object_or_404(Campaign, pk=pk)
    get_object_or_404(CampaignStep, pk=step_id, campaign=c).delete()
    return _back(c)


@login_required
@require_POST
def step_move(request, pk, step_id):
    c = get_object_or_404(Campaign, pk=pk)
    steps = list(c.steps.all())
    i = next((n for n, s in enumerate(steps) if s.pk == step_id), None)
    j = None if i is None else i + (-1 if request.POST.get('dir') == 'up' else 1)
    if i is not None and 0 <= j < len(steps):
        steps[i], steps[j] = steps[j], steps[i]
        for n, s in enumerate(steps, 1):
            if s.position != n:
                s.position = n
                s.save(update_fields=['position'])
    return _back(c)


@login_required
@require_POST
def people_add(request, pk):
    c = get_object_or_404(Campaign, pk=pk)
    last = c.people.order_by('-position').first()
    pos = (last.position if last else 0) + 1
    for p in parse_people(request.POST.get('people', '')):
        CampaignPerson.objects.create(campaign=c, position=pos, **p)
        pos += 1
    return _back(c)


@login_required
@require_POST
def person_save(request, pk, person_id):
    c = get_object_or_404(Campaign, pk=pk)
    p = get_object_or_404(CampaignPerson, pk=person_id, campaign=c)
    for f in ('name', 'title', 'company', 'email', 'phone', 'linkedin_url', 'note'):
        if f in request.POST:
            setattr(p, f, request.POST[f].strip())
    if p.name:
        p.save()
    return _back(c)


@login_required
@require_POST
def person_delete(request, pk, person_id):
    c = get_object_or_404(Campaign, pk=pk)
    get_object_or_404(CampaignPerson, pk=person_id, campaign=c).delete()
    return _back(c)


@login_required
@require_POST
def outreach_toggle(request, pk):
    """Save a batch of ticks: `changes` is JSON [{person, step, on}]."""
    c = get_object_or_404(Campaign, pk=pk)
    try:
        changes = json.loads(request.POST.get('changes') or '[]')
    except ValueError:
        return JsonResponse({'error': 'bad changes'}, status=400)
    people = {p.pk: p for p in c.people.all()}
    steps = {s.pk: s for s in c.steps.all()}
    for ch in changes:
        try:
            person, step = people[int(ch['person'])], steps[int(ch['step'])]
        except (KeyError, TypeError, ValueError):
            continue
        if ch.get('on'):
            StepDone.objects.get_or_create(person=person, step=step)
        else:
            StepDone.objects.filter(person=person, step=step).delete()
    return JsonResponse({'saved': len(changes)})
