"""Action funnel and journey Sankey from PostHog: how far client users get in BioLens, across app-prod and Neuland."""
from collections import Counter, defaultdict

from django.core.cache import cache

from . import posthog

PROJECTS = {234813: 'app-prod', 600726: 'Neuland'}

# Ordered ladder of what a user can do in BioLens. A user is counted at the furthest rung they reached in the window.
STEPS = [
    ('visit', 'Opened BioLens', 'Any page view or tracked event'),
    ('look', 'Looked at a company', 'Opened a company profile, the company list or a workspace company'),
    ('dig', 'Dug into the intel', 'Read an assessment, asked the AI, generated a report or switched profile tabs'),
    ('work', 'Worked a lead', 'Assigned a lead, changed status, scored, added to a workspace or filtered'),
    ('contact', 'Got a contact', 'Added or downloaded decision makers'),
    ('reach', 'Sent outreach', 'Used the email composer to send'),
]
STEP_EVENTS = {
    'look': ['company_profile:viewed', 'all_companies:viewed', 'all_accounts:viewed', 'biolens_search:recent_workspace_click'],
    'dig': ['company_profile:assessment_viewed', 'company_profile:ask_ai_click', 'company_profile:view_tab_click', 'chat:user_message_submit',
            'chat:generate_report_click', 'chat:download_report_click'],
    'work': ['workspace_companies:lead_assigned', 'workspace_companies:account_status_changed', 'workspace_companies:internal_score_updated',
             'workspace_companies:company_added', 'workspace_companies:filter_applied', 'workspace:created'],
    'contact': ['decision_makers:added', 'decision_makers:list_downloaded'],
    'reach': ['outreach:email_used'],
}
EVENT_STEP = {e: k for k, evs in STEP_EVENTS.items() for e in evs}
KEYS = [k for k, _, _ in STEPS]
LABEL = {k: l for k, l, _ in STEPS}
LABEL['stop'] = 'Stopped here'


def _users(days):
    """{(project, email): {step: first time}} for client users in the window."""
    where = posthog._where(days)
    events = posthog._in(list(EVENT_STEP))
    out = defaultdict(dict)
    for pid in posthog.project_ids():
        for email, ev, ts in posthog.hql(
                "SELECT person.properties.email, event, min(timestamp) FROM events WHERE %s AND event IN (%s) "
                "GROUP BY person.properties.email, event LIMIT 20000" % (where, events), pid):
            step = EVENT_STEP[ev]
            seen = out[(pid, email.lower())]
            seen[step] = min(seen[step], ts) if step in seen else ts
        for email, ts in posthog.hql(
                "SELECT person.properties.email, min(timestamp) FROM events WHERE %s AND event = '$pageview' "
                "GROUP BY person.properties.email LIMIT 20000" % where, pid):
            out[(pid, email.lower())].setdefault('visit', ts)
    for seen in out.values():  # anyone with a tracked event has opened the app, even without a page view
        seen.setdefault('visit', min(seen.values()))
    return {k: v for k, v in out.items()}


def users(days):
    k = 'posthog-funnel-%d' % days
    data = cache.get(k)
    if data is None:
        data = _users(days)
        cache.set(k, data, 300)
    return data


def build(accounts, days):
    """Funnel rows, journey Sankey and the people who stopped at each rung."""
    by_domain = posthog.by_domain_of(accounts)
    people = []
    for (pid, email), seen in users(days).items():
        acct = posthog.match_account(email, by_domain)
        # journey: opening the app is always first, then the order each other rung was first reached
        order = ['visit'] + sorted((s for s in seen if s != 'visit'), key=lambda s: (seen[s], KEYS.index(s)))
        people.append({'email': email, 'pid': pid, 'account': acct, 'path': order, 'far': max(KEYS.index(s) for s in seen)})
    total = len(people)
    reached = Counter()
    for p in people:
        for i in range(p['far'] + 1):
            reached[i] += 1
    stopped = defaultdict(list)
    for p in people:
        if p['far'] < len(KEYS) - 1:
            stopped[p['far']].append(p)
    rows = []
    for i, (key, label, hint) in enumerate(STEPS):
        n = reached[i]
        prev = reached[i - 1] if i else n
        who = sorted(stopped[i], key=lambda p: (p['account'] is None, p['account'].name if p['account'] else p['email']))
        rows.append({'key': key, 'label': label, 'hint': hint, 'n': n, 'pct': round(n * 100 / total) if total else 0,
                     'width': round(n * 100 / total, 1) if total else 0, 'conv': round(n * 100 / prev) if prev else 0,
                     'lost': prev - n if i else 0, 'stopped': len(who),
                     'who': [{'email': p['email'], 'name': p['account'].name if p['account'] else '', 'pid': p['pid'],
                              'project': PROJECTS.get(p['pid'], str(p['pid']))} for p in who[:10]], 'more': max(len(who) - 10, 0)})
    return {'total': total, 'rows': rows, 'sankey': sankey([p['path'] for p in people]) if total else None,
            'by_project': dict(Counter(PROJECTS.get(p['pid'], str(p['pid'])) for p in people))}


def sankey(paths, width=1200, height=440, node_w=14, pad=20, label_w=170):
    """Lay out a left-to-right journey Sankey. Column i is the i-th rung a user first reached; 'stop' is where their path ends."""
    cols = len(KEYS)
    links = Counter()
    nodes = Counter()
    for path in paths:
        for i, step in enumerate(path[:cols]):
            nodes[(i, step)] += 1
            if i + 1 < min(len(path), cols):
                links[((i, step), (i + 1, path[i + 1]))] += 1
        if len(path) < cols:
            nodes[(len(path), 'stop')] += 1
            links[((len(path) - 1, path[-1]), (len(path), 'stop'))] += 1
    n_users = len(paths)
    order = KEYS + ['stop']
    maxnodes = max(sum(1 for (c, _) in nodes if c == i) for i in range(cols))
    scale = (height - pad * (maxnodes - 1)) / n_users
    left = 16  # the last column's labels sit to its right, so it keeps label_w of room
    xs = [left + (width - left - label_w) * i / (cols - 1) for i in range(cols)]
    pos = {}
    for c in range(cols):
        col = sorted([k for k in nodes if k[0] == c], key=lambda k: order.index(k[1]))
        h = sum(nodes[k] * scale for k in col) + pad * (len(col) - 1)
        y = (height - h) / 2 if col else 0
        for k in col:
            pos[k] = {'x': xs[c] - node_w / 2, 'y': y, 'h': nodes[k] * scale, 'out': 0, 'in': 0}
            y += nodes[k] * scale + pad
    out_links = []
    for (a, b), v in sorted(links.items(), key=lambda kv: (pos[kv[0][0]]['y'], pos[kv[0][1]]['y'])):
        pa, pb = pos[a], pos[b]
        w = v * scale
        y0 = pa['y'] + pa['out'] + w / 2
        y1 = pb['y'] + pb['in'] + w / 2
        pa['out'] += w
        pb['in'] += w
        x0, x1 = pa['x'] + node_w, pb['x']
        xm = (x0 + x1) / 2
        out_links.append({'d': 'M%.1f,%.1f C%.1f,%.1f %.1f,%.1f %.1f,%.1f' % (x0, y0, xm, y0, xm, y1, x1, y1), 'w': round(max(w, 0.8), 1),
                          'step': b[1] if b[1] == 'stop' else a[1], 'title': '%s → %s: %d user%s' % (LABEL[a[1]], LABEL[b[1]], v, '' if v == 1 else 's')})
    out_nodes = []
    for (c, step), p in pos.items():
        out_nodes.append({'x': round(p['x'], 1), 'y': round(p['y'], 1), 'h': round(max(p['h'], 1.5), 1), 'w': node_w, 'step': step,
                          'label': LABEL[step], 'n': nodes[(c, step)], 'tx': round(p['x'] + node_w + 8, 1),
                          'ty': round(p['y'] + max(p['h'], 1.5) / 2, 1)})
    heads = [{'x': round(x - node_w / 2, 1), 'text': 'Step %d' % i if i else 'Start'} for i, x in enumerate(xs)]
    return {'w': width, 'h': height, 'nodes': out_nodes, 'links': out_links, 'heads': heads}
