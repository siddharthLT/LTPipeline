"""The pipeline digest email: accounts above 25% probability (each with a buying-thesis button) and the ten most recent open actions."""
import datetime
import json
import os
import time
import urllib.error
import urllib.request
from html import escape

from .models import Account, Task

MIN_SCORE = 25
TOP_ACTIONS = 10
DEFAULT_BASE = 'https://lt-pipeline.vercel.app'
DEFAULT_FROM = 'Lunartree GTM <notifications@lunartreedata.live>'

TEAL, TEAL_PRESS, TEAL_50, INK, INK_2, INK_3, LINE = '#035F62', '#024C4F', '#F0F9F9', '#292D2E', '#5D6668', '#9FA7A8', '#E3E8E8'
FONT = "Geist,-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"


def base_url():
    return os.environ.get('DIGEST_BASE_URL', DEFAULT_BASE).rstrip('/')


def gather(today=None):
    """{'accounts': pipeline accounts above MIN_SCORE (clients at 100% left out), best first, 'tasks': the newest open actions on accounts still in the pipeline}."""
    today = today or datetime.date.today()
    accounts = sorted((a for a in Account.objects.prefetch_related('stage_progress') if MIN_SCORE < a.score < 100),
                      key=lambda a: (-a.score, a.name.lower()))
    tasks = [t for t in Task.objects.filter(done=False).select_related('account').prefetch_related('account__stage_progress').order_by('-created_at', '-id')
             if t.account.score < 100]  # score 100 = already a client, so not pipeline
    return {'accounts': accounts, 'tasks': tasks[:TOP_ACTIONS], 'open_total': len(tasks), 'overdue': sum(1 for t in tasks if t.due_date and t.due_date < today), 'today': today}


def _button(href, label, solid=True, small=False):
    bg, fg = (TEAL, '#FFFFFF') if solid else ('#FFFFFF', TEAL)
    pad = '8px 16px' if small else '13px 28px'
    return ('<a href="%s" style="display:inline-block;background:%s;color:%s;border:1px solid %s;border-radius:999px;padding:%s;font-size:%s;'
            'font-weight:600;text-decoration:none;font-family:%s;">%s</a>' % (escape(href), bg, fg, TEAL, pad, '12px' if small else '14px', FONT, escape(label)))


def _pill(text, bg, fg):
    return '<span style="display:inline-block;background:%s;color:%s;border-radius:999px;padding:3px 10px;font-size:11px;font-weight:600;font-family:%s;">%s</span>' % (bg, fg, FONT, text)


def _short(text, n=110):
    text = ' '.join(text.split())
    return text if len(text) <= n else text[:n].rsplit(' ', 1)[0].rstrip(',;:') + '…'


def _stat(n, label, color=TEAL):
    return ('<td width="33%%" style="padding:0 4px;"><table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="background:%s;border-radius:12px;"><tr>'
            '<td align="center" style="padding:16px 6px;font-family:%s;"><div style="font-size:30px;font-weight:700;color:%s;line-height:1;">%s</div>'
            '<div style="font-size:11px;color:%s;margin-top:6px;font-weight:600;">%s</div></td></tr></table></td>' % (TEAL_50, FONT, color, n, INK_2, label))


def _track(done):
    """Ten segments, one per deal stage, filled for the stages that are done."""
    cells = ''.join('<td width="10%%" style="padding:0 1px;"><div style="height:7px;border-radius:2px;background:%s;font-size:0;line-height:0;">&nbsp;</div></td>' % (TEAL if i in done else '#DCE5E5')
                    for i in range(1, 11))
    return '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="margin-top:9px;"><tr>%s</tr></table>' % cells


def render(data=None, name=''):
    """(subject, html, text)."""
    data = data or gather()
    base, today = base_url(), data['today']
    accounts, tasks = data['accounts'], data['tasks']
    subject = 'Pipeline digest · %d account%s above %d%% · %s' % (len(accounts), '' if len(accounts) == 1 else 's', MIN_SCORE, today.strftime('%b %-d'))

    cards = []
    for a in accounts:
        cards.append(
            '<tr><td style="padding:0 0 10px;"><table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="border:1px solid %(line)s;border-radius:14px;"><tr>'
            '<td width="64" align="center" valign="middle" style="padding:16px 0 16px 16px;"><div style="width:44px;height:44px;line-height:44px;border-radius:12px;background:%(teal)s;color:#FFFFFF;'
            'font-size:19px;font-weight:700;text-align:center;font-family:%(font)s;">%(ini)s</div></td>'
            '<td valign="middle" style="padding:16px 12px;font-family:%(font)s;">'
            '<div style="font-size:16px;font-weight:700;color:%(ink)s;">%(name)s</div>'
            '<div style="margin-top:5px;">%(stage)s</div>%(track)s</td>'
            '<td align="right" valign="middle" style="padding:16px 16px 16px 0;white-space:nowrap;font-family:%(font)s;">'
            '<div style="font-size:28px;font-weight:700;color:%(teal)s;line-height:1;">%(score)d<span style="font-size:15px;">%%</span></div>'
            '<div style="margin-top:10px;">%(btn)s</div></td></tr></table></td></tr>'
            % {'line': LINE, 'teal': TEAL, 'font': FONT, 'ink': INK, 'ini': escape(a.name[:1].upper()), 'name': escape(a.name),
               'stage': _pill(escape(a.furthest_stage_name), TEAL_50, TEAL), 'track': _track(a.done_stages), 'score': a.score,
               'btn': _button('%s/accounts/%d/' % (base, a.pk), 'Buying thesis', small=True)})
    accounts_html = ''.join(cards) or '<tr><td style="padding:14px 0;font-size:14px;color:%s;font-family:%s;">No accounts are above %d%% yet.</td></tr>' % (INK_2, FONT, MIN_SCORE)

    items = []
    for i, t in enumerate(tasks, 1):
        chips = [_pill(escape(t.account.name), TEAL_50, TEAL)]
        if t.owner:
            chips.append(_pill(escape(t.owner), '#F2F4F4', INK_2))
        if t.due_date:
            late = t.due_date < today
            chips.append(_pill('%s %s' % ('Overdue' if late else 'Due', t.due_date.strftime('%b %-d')), '#FEE4E2' if late else '#FEF0C7', '#B42318' if late else '#93370D'))
        items.append(
            '<tr><td style="padding:0 0 10px;"><table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="background:#FFFFFF;border:1px solid %s;border-radius:12px;"><tr>'
            '<td width="46" valign="top" align="center" style="padding:14px 0 14px 14px;"><div style="width:26px;height:26px;line-height:26px;border-radius:50%%;background:%s;color:%s;font-size:12px;font-weight:700;text-align:center;font-family:%s;">%d</div></td>'
            '<td style="padding:13px 14px 13px 8px;font-family:%s;"><div style="font-size:14px;color:%s;line-height:1.4;font-weight:500;">%s</div>'
            '<div style="margin-top:8px;">%s</div></td></tr></table></td></tr>'
            % (LINE, TEAL_50, TEAL, FONT, i, FONT, INK, escape(_short(t.title)), ' '.join(chips)))
    actions_html = ''.join(items) or '<tr><td style="padding:14px 0;font-size:14px;color:%s;font-family:%s;">No open actions.</td></tr>' % (INK_2, FONT)
    more = data['open_total'] - len(tasks)

    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>%(subject)s</title></head>
<body style="margin:0;padding:0;background:#F4F7F7;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">%(pre)s</div>
<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="background:#F4F7F7;"><tr><td align="center" style="padding:28px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%%;max-width:600px;background:#FFFFFF;border-radius:18px;overflow:hidden;border:1px solid %(line)s;">
<tr><td style="background:%(teal)s;padding:30px 32px 26px;font-family:%(font)s;">
<div style="font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:#A9EBEE;">Lunartree &middot; Pipeline digest</div>
<div style="font-size:28px;font-weight:700;color:#FFFFFF;margin-top:8px;line-height:1.2;">%(hello)s</div>
<div style="font-size:14px;color:#D7F3F4;margin-top:6px;">%(date)s</div></td></tr>
<tr><td style="padding:22px 28px 4px;"><table role="presentation" width="100%%" cellpadding="0" cellspacing="0"><tr>%(stats)s</tr></table></td></tr>
<tr><td style="padding:26px 32px 12px;font-family:%(font)s;">
<div style="font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:%(teal)s;">Worth a closer look</div>
<div style="font-size:20px;font-weight:700;color:%(ink)s;margin-top:6px;">Above %(min)d%% probability</div></td></tr>
<tr><td style="padding:0 32px 6px;"><table role="presentation" width="100%%" cellpadding="0" cellspacing="0">%(accounts)s</table></td></tr>
<tr><td style="padding:24px 32px 12px;font-family:%(font)s;">
<div style="font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:%(teal)s;">Most recent</div>
<div style="font-size:20px;font-weight:700;color:%(ink)s;margin-top:6px;">Top %(top)d open actions</div></td></tr>
<tr><td style="padding:0 32px 6px;"><table role="presentation" width="100%%" cellpadding="0" cellspacing="0">%(actions)s</table></td></tr>
<tr><td align="center" style="padding:14px 32px 34px;font-family:%(font)s;">%(all)s%(more)s</td></tr>
<tr><td style="background:%(tint)s;padding:16px 32px;font-family:%(font)s;font-size:11px;color:%(ink2)s;line-height:1.5;">Lunartree internal &middot; pipeline tracker. Probability is the share of deal stages done. Accounts that have reached 100%% are left out.</td></tr>
</table></td></tr></table></body></html>''' % {
        'subject': escape(subject), 'pre': escape('%d accounts above %d%% and your %d newest open actions' % (len(accounts), MIN_SCORE, len(tasks))),
        'line': LINE, 'teal': TEAL, 'font': FONT, 'ink': INK, 'ink2': INK_2, 'tint': TEAL_50, 'min': MIN_SCORE, 'top': TOP_ACTIONS,
        'hello': 'Hi %s' % escape(name.split()[0]) if name else 'Your pipeline today', 'date': today.strftime('%A, %B %-d'),
        'stats': _stat(len(accounts), 'above %d%%' % MIN_SCORE) + _stat(data['open_total'], 'open actions') + _stat(data['overdue'], 'overdue', '#B42318' if data['overdue'] else TEAL),
        'accounts': accounts_html, 'actions': actions_html, 'all': _button(base + '/actions/', 'See all actions'),
        'more': ('<div style="font-size:12px;color:%s;margin-top:12px;">+ %d more open action%s on the actions page</div>' % (INK_2, more, '' if more == 1 else 's')) if more > 0 else ''}

    lines = ['Pipeline digest · %s' % today.strftime('%A, %b %-d'), '', 'Accounts above %d%% probability' % MIN_SCORE]
    lines += ['- %s (%d%%, %s): %s/accounts/%d/' % (a.name, a.score, a.furthest_stage_name, base, a.pk) for a in accounts]
    lines += ['', 'Top %d open actions' % TOP_ACTIONS]
    lines += ['- %s: %s%s%s' % (t.account.name, t.title, ' (%s)' % t.owner if t.owner else '', ' due %s' % t.due_date.strftime('%b %-d') if t.due_date else '') for t in tasks]
    lines += ['', 'See all actions: %s/actions/' % base]
    return subject, html, '\n'.join(lines)


class SendError(Exception):
    pass


def send(to, subject, html, text):
    key = os.environ.get('RESEND_KEY') or os.environ.get('RESEND_API_KEY')
    if not key:
        raise SendError('RESEND_KEY is not set')
    body = json.dumps({'from': os.environ.get('DIGEST_FROM', DEFAULT_FROM), 'to': [to], 'subject': subject, 'html': html, 'text': text}).encode()
    req = urllib.request.Request('https://api.resend.com/emails', data=body, method='POST',
                                 headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json', 'User-Agent': 'lunartree-pipeline/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get('id')
    except urllib.error.HTTPError as e:
        raise SendError('Resend answered %s: %s' % (e.code, e.read().decode()[:300]))
    except urllib.error.URLError as e:
        raise SendError('Could not reach Resend: %s' % e.reason)


def send_digest(emails=None):
    """Send the digest to each address (default: every active recipient). Returns [(email, id or error)]."""
    from .models import DigestRecipient
    if emails is None:
        people = [(r.email, r.name) for r in DigestRecipient.objects.filter(active=True)]
    else:
        names = dict(DigestRecipient.objects.filter(email__in=emails).values_list('email', 'name'))
        people = [(e, names.get(e, '')) for e in emails]
    data = gather()
    out = []
    for i, (email, name) in enumerate(people):
        if i:
            time.sleep(0.6)  # Resend allows about two requests a second
        subject, html, text = render(data, name)
        try:
            out.append((email, send(email, subject, html, text)))
        except SendError as e:
            out.append((email, 'ERROR: %s' % e))
    return out
