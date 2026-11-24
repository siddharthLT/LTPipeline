"""AI summaries for the Product usage tabs. Each tab sends OpenAI only that tab's own numbers, so a summary never strays into another view."""
import json
import os
import urllib.error
import urllib.request
from collections import Counter, defaultdict

from . import funnel, posthog

TABS = ('overview', 'funnel', 'accounts', 'recordings', 'digests', 'users', 'daily', 'unmatched')
SECTIONS = [('highlights', 'Key highlights'), ('insights', 'General insights'), ('outliers', 'Outliers'), ('risks', 'Risks')]

SCOPE = {
    'overview': 'the overall pulse: daily activity, how engaged users are (Power/Active/Browser/Low tiers), what features get used and which are unused, and which accounts are most active or quiet',
    'funnel': 'only the action funnel: step-by-step conversion, where users drop off, the biggest losses, the common paths people take, and which accounts have users stuck at which step. Do not comment on overall activity, engagement tiers or individual users beyond who is stuck where',
    'accounts': 'account-level usage: which tracker accounts are using BioLens, how much, how deeply, and which accounts with a high deal stage are quiet',
    'recordings': 'only session recordings: how long sessions are, how active, which areas and moments appear, rage clicks and errors, and which accounts or sessions stand out. Do not comment on funnel, tiers or overall usage',
    'digests': 'only the scheduled digest emails: which accounts received them, which were skipped and why (opted out, no companies), and which recipients have never opened BioLens. Do not comment on in-app usage beyond whether a recipient has ever opened it',
    'users': 'individual users: engagement tiers, who is a power user, who has stopped, and unusual patterns per person',
    'daily': 'the day-by-day rhythm: busiest and quietest days, spikes, gaps and which accounts drive them',
    'unmatched': 'users whose email domain does not match a tracker account: who they are, how much they use it and whether any should be added to the pipeline',
}


class NotConfigured(Exception):
    pass


def _quiet(accounts, using):
    return [{'account': a.name, 'furthest_stage': a.furthest_stage, 'deal_value': a.deal_value}
            for a in sorted((a for a in accounts if a.pk not in using), key=lambda a: -a.furthest_stage)[:25]]


def payload(tab, accounts, days):
    """The numbers for one tab, without email addresses."""
    if tab == 'funnel':
        f = funnel.build(accounts, days)
        return {'users_in_funnel': f['total'], 'by_project': f['by_project'],
                'steps': [{'step': r['label'], 'users_reached': r['n'], 'pct_of_all': r['pct'], 'pct_of_previous_step': r['conv'],
                           'users_whose_furthest_step_is_this': r['stopped'],
                           'who_stopped_here': [(w['name'] or 'not in tracker') + ' (' + w['project'] + ')' for w in r['who']]} for r in f['rows']],
                'most_common_paths_with_user_counts': f['top_paths']}
    if tab == 'digests':
        from . import digests
        d = digests.build(accounts, days)
        return {'job_runs_in_window': d['run_days'], 'accounts_receiving_digests': d['receiving_accounts'], 'people_receiving': d['people_receiving'],
                'recipients_who_never_opened_biolens': d['never_opened_people'], 'accounts_where_nobody_ever_opened_biolens': d['digest_only_accounts'],
                'per_account': [{'account': c['account'].name, 'furthest_stage': c['account'].furthest_stage, 'sent': c['sent'], 'skipped': c['skipped'],
                                 'recipients': c['receiving'], 'never_opened': c['never'], 'latest_run_sent': c['last'] == 'ok'} for c in d['cards']],
                'accounts_with_no_digest': [a.name for a in d['without']]}
    rows, unmatched, daily, totals = posthog.join(accounts, days)
    using = {m['account'].pk for m in rows}
    user = lambda u: {'name': u['name'] or 'unnamed', 'tier': u['tier'], 'sessions': u['sessions'], 'features_used': u['feats'], 'pages': u['pvs'],
                      'actions': u['acts'], 'ai_messages': u['ai'], 'rage_clicks': u['rage'], 'last_seen': u['last_seen']}
    acct = lambda m: {'account': m['account'].name, 'furthest_stage': m['account'].furthest_stage, 'deal_value': m['account'].deal_value,
                      'users': len(m['users']), 'events': m['evts'], 'sessions': m['sessions'], 'actions': m['acts'], 'ai_messages': m['ai'],
                      'rage_clicks': m['rage'], 'features_used': m['feats'], 'last_seen': m['last_seen'],
                      'tiers': dict(Counter(u['tier'] for u in m['users']))}
    if tab == 'overview':
        sh = posthog.shape(rows, daily, days)
        return {'totals': totals, 'tracker_accounts': len(accounts), 'accounts_using_it': len(rows),
                'daily_activity': [(d['label'], d['total'], d['acts'], d['users']) for d in sh['series'] if d['total']],
                'daily_fields': 'day, events and page views, actions, active users',
                'engagement_tiers': sh['mix'], 'feature_counts': [(f['label'], f['n']) for f in sh['features']], 'unused_features': sh['unused'],
                'most_active_accounts': [acct(m) for m in sorted(rows, key=lambda m: -m['evts'])[:12]], 'quiet_accounts': _quiet(accounts, using)}
    if tab == 'accounts':
        return {'totals': totals, 'accounts_using_it': [acct(m) for m in rows], 'quiet_accounts': _quiet(accounts, using)}
    if tab == 'users':
        return {'totals': totals, 'users': [dict(user(u), account=m['account'].name) for m in rows for u in m['users']]}
    if tab == 'daily':
        by_day, by_acct = defaultdict(lambda: {'users': 0, 'pages': 0, 'events': 0, 'actions': 0}), defaultdict(int)
        for d in daily:
            b = by_day[d['day']]
            b['users'] += 1; b['pages'] += d['pvs']; b['events'] += d['total']; b['actions'] += sum(d['counts'])
            by_acct[d['account'].name if d['account'] else 'not in tracker'] += 1
        return {'per_day': sorted(by_day.items()), 'active_user_days_by_account': dict(sorted(by_acct.items(), key=lambda kv: -kv[1]))}
    if tab == 'unmatched':
        return {'domains_not_in_tracker': [{'domain': u['domain'], 'users': u['users'], 'events': u['evts'], 'actions': u['acts']} for u in unmatched]}
    # recordings
    from .views import _recordings_context
    ctx = _recordings_context(accounts, days)
    recs = ctx['recs']
    per_acct = [{'account': p['name'], 'recordings': p['n'], 'active_seconds': p['active'], 'total_seconds': p['dur']} for p in ctx['playlists']]
    return {'recordings': len(recs), 'length_buckets': [(b['label'], b['n']) for b in ctx['buckets']], 'per_account': per_acct,
            'areas_visited': Counter(a for r in recs for a in r['areas']).most_common(12),
            'moments': Counter(d for r in recs for d in r['did']).most_common(12),
            'devices': Counter(r['device'] for r in recs), 'countries': Counter(r['country'] for r in recs).most_common(8),
            'sessions_with_errors': sum(1 for r in recs if r['errors']), 'sessions_with_rage_clicks': sum(1 for r in recs if r['rage']),
            'longest_sessions': [{'account': r['brand'], 'seconds': r['dur'], 'active_seconds': r['active'], 'clicks': r['clicks'], 'errors': r['errors'],
                                  'rage': r['rage'], 'areas': r['areas'], 'moments': r['did']} for r in sorted(recs, key=lambda r: -r['dur'])[:12]]}


PROVIDERS = [  # tried in order; a provider is skipped when its key is not set
    ('OpenAI', 'https://api.openai.com/v1/chat/completions', ('OPENAI_KEY', 'OPENAI_API_KEY'), 'OPENAI_MODEL', 'gpt-6-luna'),
    ('Groq', 'https://api.groq.com/openai/v1/chat/completions', ('GROQ_KEY', 'GROQ_API_KEY'), 'GROQ_MODEL', 'openai/gpt-oss-120b'),
]
HEADS = {'HEADLINE': 'headline', 'HIGHLIGHTS': 'highlights', 'INSIGHTS': 'insights', 'OUTLIERS': 'outliers', 'RISKS': 'risks'}


def _stream(url, key, model, system, data):
    """Text pieces from one chat-completions endpoint (OpenAI and Groq share the format) as they arrive."""
    req = urllib.request.Request(
        url, data=json.dumps({'model': model, 'stream': True, 'messages': [{'role': 'system', 'content': system},
                                                                              {'role': 'user', 'content': json.dumps(data, default=str)}]}).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key, 'User-Agent': 'pipelinetracker/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=55) as r:
            for raw in r:
                line = raw.decode('utf-8', 'replace').strip()
                if not line.startswith('data:') or line == 'data: [DONE]':
                    continue
                choices = json.loads(line[5:]).get('choices') or []
                piece = choices[0].get('delta', {}).get('content') if choices else None
                if piece:
                    yield piece
    except urllib.error.HTTPError as e:
        raise RuntimeError('answered %s: %s' % (e.code, e.read()[:160].decode(errors='replace')))


def parse(text):
    """HEADLINE:/HIGHLIGHTS:/... text into {headline, highlights, insights, outliers, risks}. Works on partial text too."""
    out = {'headline': '', 'highlights': [], 'insights': [], 'outliers': [], 'risks': []}
    section = None
    for line in text.splitlines():
        s = line.strip()
        word, sep, rest = s.partition(':')
        if sep and word.strip('*# ').upper() in HEADS:
            section = HEADS[word.strip('*# ').upper()]
            if section == 'headline':
                out['headline'] = rest.strip()
            continue
        if not s or section is None:
            continue
        if section == 'headline':
            out['headline'] = (out['headline'] + ' ' + s).strip()
        else:
            if s[0] in '-*•' or not out[section]:
                out[section].append(s.lstrip('-*• ').strip())
            else:  # a bullet that wrapped onto the next line
                out[section][-1] += ' ' + s
    return out


def generate_stream(tab, accounts, days):
    """Yield events {'t': 'delta'|'reset'|'done'|'error', ...}. OpenAI first, then Groq if OpenAI fails; 'done' carries the parsed summary."""
    system = (
        "You are a sharp product and sales analyst for Lunartree, which sells BioLens (commercial intelligence for CDMOs, CROs and suppliers). "
        "You are looking at one tab of the Product usage dashboard, covering the last %d days. Write ONLY about this scope: %s. "
        "Use only the numbers given and never invent any. Name the accounts, steps or sessions involved and quote the actual numbers. "
        "Be plain and specific, not generic. If the data is thin, say so. Reply in exactly this plain-text layout, no markdown, no extra text:\n"
        "HEADLINE: one sentence\nHIGHLIGHTS:\n- 2 to 4 short bullets\nINSIGHTS:\n- 2 to 5 bullets\n"
        "OUTLIERS:\n- 0 to 4 bullets about things far from the rest\nRISKS:\n- 0 to 4 bullets about what could go wrong or is going quiet\n"
        "Each bullet is one or two sentences." % (days, SCOPE[tab]))
    data = payload(tab, accounts, days)
    providers = [(n, u, next((os.environ[k] for k in keys if os.environ.get(k)), ''), os.environ.get(m, d)) for n, u, keys, m, d in PROVIDERS]
    providers = [p for p in providers if p[2]]
    if not providers:
        raise NotConfigured('Neither OPENAI_KEY nor GROQ_KEY is set')
    errors = []
    for name, url, key, model in providers:
        text = ''
        try:
            for piece in _stream(url, key, model, system, data):
                text += piece
                yield {'t': 'delta', 'v': piece}
            result = parse(text)
            if not (result['headline'] and (result['highlights'] or result['insights'])):
                raise RuntimeError('returned an empty summary')
            yield {'t': 'done', 'content': result, 'provider': name}
            return
        except Exception as e:
            errors.append('%s %s' % (name, e))
            yield {'t': 'reset'}  # discard what was shown and try the next provider
    raise RuntimeError('; '.join(errors))
