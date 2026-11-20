"""Download a buying thesis as JSON (all the data) or PDF (a report, one page per section)."""
import datetime
import io
import json
from html import escape

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.text import slugify

from .stages import STAGE_NAMES, STAGE_WEIGHTS, USAGE_CHECKS

TEXT_FIELDS_BULLETS = ('buyer', 'champion', 'users', 'blockers', 'must_happen', 'before_pay', 'expand_when', 'why_not', 'icp')


def _lines(value):
    return [line.strip().lstrip('-•').strip() for line in (value or '').splitlines() if line.strip()]


def _date(d, fmt='%b %-d, %Y'):
    return d.strftime(fmt) if d else ''


# ---------------------------------------------------------------- JSON
def account_payload(account):
    """Everything the buying thesis page shows, plus the raw fields, as plain data."""
    today = datetime.date.today()
    schedule = account.schedule()
    path = account.path_steps()
    commercial = account.commercial_nodes()
    raw = {f.name: getattr(account, f.name) for f in account._meta.fields}
    raw['segment_label'] = account.get_segment_display() if account.segment else ''
    return {
        'exported_on': today.isoformat(),
        'company': {
            'id': account.pk, 'name': account.name, 'domain': account.domain, 'segment': raw['segment_label'],
            'deal_value': account.deal_value, 'sales_marketing_team': account.sales_marketing_team,
            'team_size_source': account.team_size_source, 'advisors': account.advisors,
            'what_they_do': account.what_they_do, 'what_they_service': account.what_they_service,
            'who_they_service': account.who_they_service, 'modality': account.modality,
            'therapeutic_focus': account.therapeutic_focus, 'trial_phase': account.trial_phase,
            'geography': account.geography, 'icp': _lines(account.icp), 'icp_source': account.icp_source,
        },
        'deal_snapshot': {
            'current_stage': account.furthest_stage_name, 'current_step': account.furthest_stage,
            'probability_of_closing_percent': account.score,
            'buyer': _lines(account.buyer), 'champion': _lines(account.champion), 'users': _lines(account.users),
            'blockers': _lines(account.blockers), 'must_happen': _lines(account.must_happen),
            'biggest_risk': account.biggest_risk,
            'next_actions': [{'title': t.title, 'owner': t.owner, 'due_date': t.due_date, 'done': t.done}
                             for t in account.tasks.all()],
            'usage_checks': {'tried': account.usage_tried, 'reached_value': account.usage_value,
                             'onboarded': account.usage_onboarded, 'integration_started': account.integration_started},
        },
        'buying_thesis': {
            'why_buy': account.why_buy, 'pain_now': account.pain_now, 'who_cares': account.who_cares,
            'buying_first': account.buying_first, 'before_pay': _lines(account.before_pay),
            'expand_when': _lines(account.expand_when), 'expansion_trigger': account.expansion_trigger,
            'why_not': _lines(account.why_not),
            'commercial_path': [{'step': n['name'], 'date': n['date'], 'status': n['label'], 'date_is_estimate': n['auto'],
                                 'value': n['value'], 'note': n['note']} for n in commercial],
            'trial_note': account.trial_note, 'expected_credits': account.expected_credits,
            'pilot_value': account.pilot_value, 'pilot_date': account.pilot_date,
            'annual_value': account.annual_value, 'annual_date': account.annual_date,
        },
        'stage_tracker': [{
            'step': r['num'], 'name': r['name'], 'weight_percent': r['weight'], 'done': r['done'],
            'evidence': r['why'], 'target_date': r['target_date'],
            'criteria': [{'key': c['key'], 'label': c['label'], 'met': c['met']} for c in r['criteria']],
        } for r in account.stage_rows()],
        'predicted_schedule': [{'step': s['num'], 'name': s['name'], 'done': s['done'], 'date': s['date'],
                                'date_is_override': s['override'], 'is_gap': s['gap'], 'overdue': s['overdue']}
                               for s in schedule],
        'path_after_demo': [{'name': p['name'], 'drivers': p['drivers'], 'percent': p['pct'], 'state': p['state']}
                            for p in path],
        'meetings': [{'title': m.title, 'held_on': m.held_on, 'who': m.who, 'problems': m.problems, 'tools': m.tools,
                      'showed': m.showed, 'questions': m.questions, 'landed': m.landed, 'pushback': m.pushback}
                     for m in account.meetings.all()],
        'timeline': [{'date': e.date, 'kind': e.kind, 'text': e.text} for e in account.events.all()],
        'sent_emails': [{'sent_on': e.sent_on, 'subject': e.subject, 'recipients': e.recipients, 'body': e.body}
                        for e in account.emails.all()],
        'raw_fields': raw,
    }


def filename(account, ext):
    return f'{slugify(account.name) or "account"}-buying-thesis.{ext}'


def json_bytes(account):
    return json.dumps(account_payload(account), cls=DjangoJSONEncoder, indent=2, ensure_ascii=False).encode('utf-8')


# ---------------------------------------------------------------- PDF
INK, INK2, LINE = '#292D2E', '#5D6668', '#D8DDDE'
TEAL, MARK, TEAL50, TEAL200, ORANGE = '#035F62', '#078E93', '#F0F9F9', '#A9EBEE', '#DC5800'
PAGE_W, PAGE_H = 595.27, 841.89
MARGIN = 44
HEAD_H, FOOT_H = 86, 40
FRAME_W = PAGE_W - 2 * MARGIN
FRAME_H = PAGE_H - MARGIN - HEAD_H - FOOT_H - 8
FIT_H = FRAME_H - 6
SCALE_MIN, SCALE_MAX = 0.68, 1.7
BASE = 9.6


def _fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    fonts = settings.BASE_DIR / 'static' / 'fonts' / 'pdf'
    for name, file in (('Geist', 'Geist-Regular.ttf'), ('Geist-Bold', 'Geist-SemiBold.ttf'), ('GeistMono', 'GeistMono-Regular.ttf')):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(fonts / file)))
    pdfmetrics.registerFontFamily('Geist', normal='Geist', bold='Geist-Bold', italic='Geist', boldItalic='Geist-Bold')


_REPLACE = {'→': ' to ', '←': ' from ', '✓': '', '–': '-', '—': '-', '‑': '-', ' ': ' ', '≈': '~', '≥': '>=', '≤': '<=', '×': 'x'}


def _clean(text):
    from reportlab.pdfbase import pdfmetrics
    cmap = pdfmetrics.getFont('Geist').face.charToGlyph
    out = []
    for ch in str(text):
        ch = _REPLACE.get(ch, ch)
        out.append(ch if all(ord(c) in cmap or c in '\n' for c in ch) else '')
    return ''.join(out)


class _Ctx:
    """Style factory for one fit attempt: s scales type, g stretches spacing, lim shortens long text."""

    def __init__(self, s, g=1.0, lim=None):
        from reportlab.lib.colors import HexColor
        from reportlab.lib.styles import ParagraphStyle
        self.s, self.g, self.lim = s, g, lim
        self.C = HexColor
        self.PS = ParagraphStyle
        self.body = self.style('body', BASE, INK, lead=1.42)
        self.small = self.style('small', BASE - 1.4, INK2, lead=1.38)
        self.label = self.style('label', BASE - 1.9, TEAL, font='Geist-Bold', lead=1.3)
        self.h3 = self.style('h3', BASE + 1.4, INK, font='Geist-Bold', lead=1.3)

    def style(self, name, size, color, font='Geist', lead=1.4, **kw):
        return self.PS(name, fontName=font, fontSize=size * self.s, leading=size * self.s * lead,
                       textColor=self.C(color), **kw)

    def t(self, text):
        text = _clean(text).strip()
        if self.lim and len(text) > self.lim:
            text = text[:self.lim].rsplit(' ', 1)[0].rstrip(',.;:') + '...'
        return escape(text).replace('\n', '<br/>')

    def gap(self, pts):
        from reportlab.platypus import Spacer
        return Spacer(1, pts * self.s * self.g)

    def p(self, text, style=None):
        from reportlab.platypus import Paragraph
        return Paragraph(self.t(text), style or self.body)

    def bullets(self, items, numbered=False):
        from reportlab.platypus import Paragraph
        st = self.PS('li', parent=self.body, leftIndent=11 * self.s, bulletIndent=0, spaceAfter=2.2 * self.s * self.g)
        return [Paragraph(self.t(x), st, bulletText=(f'{i}.' if numbered else '•')) for i, x in enumerate(items, 1)]

    def value(self, text, bullet=False, numbered=False):
        """A field value: bullets for multi-line lists, a paragraph otherwise, a muted line when empty."""
        if not (text or '').strip():
            return [self.p('Not set yet', self.style('muted', BASE, '#8C9597'))]
        lines = _lines(text)
        if bullet:
            return self.bullets(lines, numbered)
        return [self.p(text)]

    def kv(self, rows, label_w=118):
        """Two-column label / value table, one hairline under each row."""
        from reportlab.platypus import Paragraph, Table, TableStyle
        data = []
        for label, cells in rows:
            data.append([Paragraph(escape(label.upper()), self.label), cells])
        label_w = label_w * (0.55 + 0.45 * max(self.s, 1))
        tbl = Table(data, colWidths=[label_w, FRAME_W - label_w])
        pad = 5.5 * self.s * self.g
        tbl.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), pad), ('BOTTOMPADDING', (0, 0), (-1, -1), pad),
            ('LINEBELOW', (0, 0), (-1, -1), 0.5, self.C(LINE)),
        ]))
        return tbl

    def question(self, num, title, body):
        """Numbered question header with its answer flowables underneath."""
        from reportlab.platypus import Paragraph
        head = Paragraph(f'<font name="GeistMono" color="{MARK}">{escape(num)}</font>&nbsp;&nbsp;{escape(_clean(title))}', self.h3)
        return [head, self.gap(3)] + list(body) + [self.gap(8)]

    def table(self, header, rows, widths, mono_cols=()):
        from reportlab.platypus import Paragraph, Table, TableStyle
        hs = self.style('th', BASE - 2, TEAL, font='Geist-Bold')
        data = [[Paragraph(escape(h.upper()), hs) for h in header]]
        data += rows
        tbl = Table(data, colWidths=widths, repeatRows=0)
        pad = 3.6 * self.s * self.g
        tbl.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), pad), ('BOTTOMPADDING', (0, 0), (-1, -1), pad),
            ('BACKGROUND', (0, 0), (-1, 0), self.C(TEAL50)),
            ('LINEBELOW', (0, 0), (-1, 0), 0.8, self.C(TEAL200)),
            ('LINEBELOW', (0, 1), (-1, -1), 0.4, self.C(LINE)),
        ]))
        return tbl

    def mono(self, text, color=INK2):
        from reportlab.platypus import Paragraph
        return Paragraph(escape(_clean(text)), self.style('mono', BASE - 1.4, color, font='GeistMono', lead=1.3))


def _kpis(c, account, next_stage, contract):
    from reportlab.platypus import Paragraph, Table, TableStyle
    when = f'{next_stage["name"]} by {_date(next_stage["date"], "%b %-d")}' if next_stage else 'No open step ahead'
    contract_line = 'Contract signed' if contract['done'] else f'Contract by {_date(contract["date"])}'
    cells = []
    for k, v, sub in (('Current pipeline stage', account.furthest_stage_name, f'Step {account.furthest_stage} of 12'),
                      ('Probability of closing', f'{account.score}%', 'From the stage score'),
                      ('Realistic timeline', when, contract_line)):
        cells.append([Paragraph(escape(k.upper()), c.label), Paragraph(escape(_clean(v)), c.style('kv', BASE + 4.5, TEAL, font='Geist-Bold', lead=1.2)),
                      Paragraph(escape(_clean(sub)), c.small)])
    w = FRAME_W / 3
    tbl = Table([[cells[0], cells[1], cells[2]]], colWidths=[w, w, w], hAlign='LEFT')
    pad = 9 * c.s * c.g
    tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, -1), c.C(TEAL50)), ('BOX', (0, 0), (0, 0), 0.6, c.C(TEAL200)),
        ('BOX', (1, 0), (1, 0), 0.6, c.C(TEAL200)), ('BOX', (2, 0), (2, 0), 0.6, c.C(TEAL200)),
        ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), pad), ('BOTTOMPADDING', (0, 0), (-1, -1), pad),
    ]))
    return tbl


# ------------------------------------------------------------ section builders (each returns flowables)
def _company_facts(account):
    first = min([e.date for e in account.events.all()] + [m.held_on for m in account.meetings.all() if m.held_on], default=None)
    last = max([e.date for e in account.events.all()] + [e.sent_on for e in account.emails.all()] +
               [m.held_on for m in account.meetings.all() if m.held_on], default=None)
    return first, last


def build_cover(c, account, ctx):
    from reportlab.platypus import Paragraph
    out = [Paragraph('<font color="%s">&#9679;</font>&nbsp;&nbsp;BUYING THESIS' % ORANGE, c.style('eb', BASE - 1.6, TEAL, font='Geist-Bold')),
           c.gap(8),
           Paragraph(escape(_clean(account.name)), c.style('title', 34, INK, font='Geist-Bold', lead=1.1)),
           c.gap(5),
           c.p(' · '.join(x for x in (account.get_segment_display() if account.segment else '', account.domain,
                                       account.deal_value and f'Deal value {account.deal_value}') if x), c.style('sub', 12, INK2, lead=1.3)),
           c.gap(18),
           _kpis(c, account, ctx['next_stage'], ctx['contract']), c.gap(20)]
    first, last = _company_facts(account)
    summary = [f'{account.name} is at step {account.furthest_stage} of 12 ({account.furthest_stage_name}), with a {account.score}% probability of closing.']
    if account.advisors:
        summary.append(f'Our connection runs through {account.advisors}.')
    if first:
        summary.append(f'First recorded touch {_date(first)}, latest {_date(last)}: {account.meetings.count()} meeting'
                       f'{"" if account.meetings.count() == 1 else "s"}, {account.emails.count()} email'
                       f'{"" if account.emails.count() == 1 else "s"} and {account.events.count()} timeline entries.')
    open_n = len(account.open_actions())
    if open_n:
        od = len(account.overdue_actions())
        summary.append(f'{open_n} open next action{"" if open_n == 1 else "s"}' + (f', {od} overdue.' if od else '.'))
    out += [Paragraph('SUMMARY', c.label), c.gap(3), c.p(' '.join(summary), c.style('lead', 12, INK, lead=1.5)), c.gap(22),
            Paragraph('IN THIS REPORT', c.label), c.gap(5)]
    rows = []
    for i, (title, _) in enumerate(ctx['toc'], 2):
        rows.append([c.mono(f'{i:02d}', MARK), c.p(title, c.style('toc', 10.5, INK, lead=1.3))])
    from reportlab.platypus import Table, TableStyle
    tbl = Table(rows, colWidths=[34, FRAME_W - 34])
    pad = 3.8 * c.s * c.g
    tbl.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                             ('TOPPADDING', (0, 0), (-1, -1), pad), ('BOTTOMPADDING', (0, 0), (-1, -1), pad),
                             ('LINEBELOW', (0, 0), (-1, -1), 0.4, c.C(LINE))]))
    out.append(tbl)
    return out


def build_snapshot(c, account, ctx):
    from reportlab.platypus import Paragraph, Table, TableStyle
    out = [_kpis(c, account, ctx['next_stage'], ctx['contract']), c.gap(10)]
    rows = [('Buyer', c.value(account.buyer, True)), ('Champion', c.value(account.champion, True)),
            ('Users', c.value(account.users, True)), ('Can block it', c.value(account.blockers, True)),
            ('What has to happen', c.value(account.must_happen, True, numbered=True)),
            ('Biggest risk', c.value(account.biggest_risk))]
    out.append(c.kv(rows))
    out.append(c.gap(10))
    out.append(Paragraph('NEXT ACTIONS', c.label))
    out.append(c.gap(3))
    tasks = list(account.tasks.all())
    if tasks:
        today = datetime.date.today()
        trows = []
        for t in tasks:
            late = not t.done and t.due_date and t.due_date < today
            status = 'Done' if t.done else ('Overdue' if late else 'Open')
            trows.append([c.p(t.title), c.p(t.owner or 'Not set', c.small), c.mono(_date(t.due_date) or 'No date'),
                          c.mono(status, ORANGE if late else (MARK if t.done else INK2))])
        out.append(c.table(['Action', 'Owner', 'Due', 'Status'], trows, [FRAME_W - 230, 70, 90, 70]))
    else:
        out.append(c.p('No next actions set yet.', c.small))
    return out


def build_thesis(c, account, ctx):
    out = c.question('Q1', f'Why would {account.name} buy BioLens?', [
        c.p('Biggest problem', c.label), c.p(account.why_buy or 'Not set yet'), c.gap(3),
        c.p('Painful right now', c.label), c.p(account.pain_now or 'Not set yet')])
    out += c.question('Q2', 'Who actually cares, and why?', c.value(account.who_cares))
    out += c.question('Q3', 'What are they buying first?', c.value(account.buying_first))
    out += c.question('Q4', 'What has to happen before they pay?', c.value(account.before_pay, True))
    expand = c.value(account.expand_when, True)
    if account.expansion_trigger:
        expand = [c.p('Trigger: ' + account.expansion_trigger)] + expand
    out += c.question('Q5', 'What would make them expand?', expand)
    nodes = ctx['commercial']
    rows = []
    for n in nodes:
        when = n['label'] or (_date(n['date']) + (' (est.)' if n['auto'] else '') if n['date'] else '')
        detail = ' · '.join(x for x in (n['value'] or n['empty'], n['note']) if x)
        rows.append([c.p(n['name']), c.mono(when), c.p(detail, c.small)])
    out += c.question('Q6', 'What is the realistic commercial path?',
                      [c.table(['Step', 'When', 'Value and note'], rows, [112, 100, FRAME_W - 212])])
    out += c.question('Q7', 'Why might they not buy?', c.value(account.why_not, True))
    return out


def build_context(c, account, ctx):
    """Where the deal stands, pinned to the foot of the short profile pages."""
    from reportlab.platypus import Paragraph
    out = [Paragraph('WHERE THIS DEAL STANDS', c.label), c.gap(4), _kpis(c, account, ctx['next_stage'], ctx['contract']), c.gap(8)]
    if (account.biggest_risk or '').strip():
        out += [Paragraph('BIGGEST RISK', c.label), c.gap(2), c.p(account.biggest_risk, c.small), c.gap(6)]
    actions = account.open_actions()
    if actions:
        t = actions[0]
        out += [Paragraph('NEXT ACTION', c.label), c.gap(2),
                c.p(t.title + (f' ({t.owner}' + (f', {_date(t.due_date)}' if t.due_date else '') + ')' if t.owner else ''), c.small)]
    return out


def build_company(c, account, ctx):
    first, last = _company_facts(account)
    rows = [('Company', [c.p(account.name, c.style('big', 13, INK, font='Geist-Bold'))]),
            ('Domain', [c.p(account.domain)]),
            ('Segment', c.value(account.get_segment_display() if account.segment else '')),
            ('Deal value', c.value(account.deal_value)),
            ('Sales and marketing team', c.value(str(account.sales_marketing_team or ''))),
            ('Team size source', c.value(account.team_size_source)),
            ('Advisors', c.value(account.advisors)),
            ('First recorded touch', c.value(_date(first))),
            ('Latest recorded touch', c.value(_date(last))),
            ('Record', [c.p(f'{account.meetings.count()} meetings, {account.emails.count()} sent emails, '
                            f'{account.events.count()} timeline entries, {len(account.tasks.all())} next actions.')])]
    return [c.kv(rows, 150)]


def build_overview(c, account, ctx):
    return [c.kv([('What they do', c.value(account.what_they_do)), ('What they service', c.value(account.what_they_service)),
                  ('Who they service', c.value(account.who_they_service))], 130)]


def build_profile(c, account, ctx):
    return [c.kv([('Modality', c.value(account.modality)), ('Therapeutic focus', c.value(account.therapeutic_focus)),
                  ('Trial phase', c.value(account.trial_phase)), ('Geography', c.value(account.geography))], 130)]


def build_icp(c, account, ctx):
    out = c.value(account.icp, True)
    if account.icp_source:
        out += [c.gap(10), c.p('SOURCE', c.label), c.gap(2), c.p(account.icp_source, c.small)]
    return out


build_company.pin = build_overview.pin = build_profile.pin = build_icp.pin = build_context


def build_stages(c, account, ctx):
    rows = []
    for r in ctx['stage_rows']:
        crit = [c.p(('Met: ' if k['met'] else 'Open: ') + k['label'], c.small) for k in r['criteria']]
        evidence = [c.p(r['why'], c.small)] if r['why'] else []
        status = 'Done' if r['done'] else ('In progress' if r['met'] else 'Open')
        rows.append([c.mono(f'{r["num"]:02d}', MARK), c.p(r['name'], c.style('sn', BASE, INK, font='Geist-Bold')),
                     c.mono(f'{status}\n{r["met"]}/{r["total"]} · {r["weight"]}%'.replace('\n', ' ')),
                     evidence + crit])
    head = [c.p(f'Score {account.score}% = the weight of every step marked done (steps 1-4 weigh 5% each, steps 5-12 weigh 10% each).', c.small), c.gap(5)]
    return head + [c.table(['#', 'Step', 'Status', 'Evidence and criteria'], rows, [24, 76, 78, FRAME_W - 178])]


def build_meeting(index):
    """One page per meeting, so a long meeting is never squeezed next to another."""
    def build(c, account, ctx):
        from reportlab.platypus import Paragraph
        from .models import MEETING_PARTS
        m = list(account.meetings.all())[index]
        out = [Paragraph(f'{escape(_clean(m.title))}', c.style('mt', BASE + 4, INK, font='Geist-Bold', lead=1.25)), c.gap(3),
               c.mono(_date(m.held_on)), c.gap(8)]
        rows = [(label, c.value(getattr(m, key))) for key, label in MEETING_PARTS if (getattr(m, key) or '').strip()]
        if rows:
            out.append(c.kv(rows, 128))
        return out
    build.pin = build_context
    return build


def build_timeline(c, account, ctx):
    from reportlab.platypus import Paragraph
    out = []
    events = list(account.events.all())
    emails = list(account.emails.all())
    if events:
        rows = [[c.mono(_date(e.date)), c.mono(e.get_kind_display(), MARK), c.p(e.text)] for e in events]
        out += [Paragraph('TIMELINE', c.label), c.gap(3), c.table(['Date', 'Type', 'What happened'], rows, [74, 54, FRAME_W - 128]), c.gap(12)]
    if emails:
        rows = [[c.mono(_date(e.sent_on)), c.p(e.subject, c.style('es', BASE, INK, font='Geist-Bold')), c.p(e.recipients, c.small)] for e in emails]
        out += [Paragraph('SENT EMAILS', c.label), c.gap(3), c.table(['Date', 'Subject', 'To and context'], rows, [74, 190, FRAME_W - 264]),
                c.gap(3), c.p('Full email text is in the JSON download.', c.small)]
    return out


def _sections(account):
    """(title, builder) for every section that has something to show."""
    sections = [('Deal snapshot', build_snapshot), ('Buying thesis in short', build_thesis),
                ('1  Company', build_company), ('2  What they do, service, and who they service', build_overview),
                ('3  Modality, focus area, phase, geography', build_profile)]
    if (account.icp or '').strip():
        sections.append(('4  Their ICP', build_icp))
    sections.append(('5  Stage tracker and score', build_stages))
    n_meetings = len(account.meetings.all())
    for i in range(n_meetings):
        label = '6  Meeting notes' + (f' ({i + 1} of {n_meetings})' if n_meetings > 1 else '')
        sections.append((label, build_meeting(i)))
    if account.events.all() or account.emails.all():
        sections.append(('7  Timeline and sent emails', build_timeline))
    return sections


def _compose(builder, account, ctx, c):
    """Section flowables for one fit attempt; a pinned card sits at the foot of the page. Returns (flowables, height)."""
    from reportlab.platypus import Spacer
    flow = builder(c, account, ctx)
    pin = getattr(builder, 'pin', None)
    pflow = pin(c, account, ctx) if pin else []

    def h(items):
        return sum(f.wrap(FRAME_W, 10 ** 6)[1] + f.getSpaceBefore() + f.getSpaceAfter() for f in items)
    main, foot = h(flow), h(pflow)
    if pflow:
        flow = flow + [Spacer(1, max(14, FIT_H - main - foot))] + pflow
        return flow, main + foot + 14
    return flow, main


def _fit(builder, account, ctx):
    """Largest type size (and then spacing) at which the whole section fits one page. Shortens text as a last resort."""
    def height(s, g, lim):
        c = _Ctx(s, g, lim)
        return _compose(builder, account, ctx, c)[1]

    for lim in (None, 900, 520, 320, 200):
        if height(SCALE_MIN, 1, lim) > FIT_H:
            continue
        lo, hi = SCALE_MIN, SCALE_MAX
        for _ in range(14):
            mid = (lo + hi) / 2
            if height(mid, 1, lim) <= FIT_H:
                lo = mid
            else:
                hi = mid
        glo, ghi = 1.0, 4.0
        for _ in range(12):
            mid = (glo + ghi) / 2
            if height(lo, mid, lim) <= FIT_H:
                glo = mid
            else:
                ghi = mid
        return _Ctx(lo, glo, lim)
    return _Ctx(SCALE_MIN, 1, 120)


def _chrome(canvas, doc, name, title, page, total, cover=False):
    from reportlab.lib.colors import HexColor
    canvas.saveState()
    canvas.setFillColor(HexColor(TEAL))
    canvas.rect(0, PAGE_H - 8, PAGE_W, 8, stroke=0, fill=1)
    if not cover:
        canvas.setFillColor(HexColor(ORANGE))
        canvas.circle(MARGIN + 3, PAGE_H - MARGIN - 4, 2.6, stroke=0, fill=1)
        canvas.setFillColor(HexColor(TEAL))
        canvas.setFont('Geist-Bold', 8.2)
        canvas.drawString(MARGIN + 12, PAGE_H - MARGIN - 7, f'BUYING THESIS · {_clean(name).upper()}')
        canvas.setFillColor(HexColor(INK))
        canvas.setFont('Geist-Bold', 19)
        canvas.drawString(MARGIN, PAGE_H - MARGIN - 36, _clean(title))
        canvas.setStrokeColor(HexColor(TEAL200))
        canvas.setLineWidth(0.8)
        canvas.line(MARGIN, PAGE_H - MARGIN - 50, PAGE_W - MARGIN, PAGE_H - MARGIN - 50)
    canvas.setStrokeColor(HexColor(LINE))
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, FOOT_H, PAGE_W - MARGIN, FOOT_H)
    canvas.setFillColor(HexColor(INK2))
    canvas.setFont('Geist', 7.6)
    canvas.drawString(MARGIN, FOOT_H - 14, f'Lunartree · BioLens pipeline tracker · exported {_date(datetime.date.today())}')
    canvas.setFont('GeistMono', 7.6)
    canvas.drawRightString(PAGE_W - MARGIN, FOOT_H - 14, f'{page} / {total}')
    canvas.restoreState()


def pdf_bytes(account):
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import Frame
    _fonts()
    sections = _sections(account)
    ctx = {'next_stage': account.next_stage, 'contract': account.schedule()[11], 'stage_rows': account.stage_rows(),
           'commercial': account.commercial_nodes(), 'toc': sections}
    total = len(sections) + 1
    buf = io.BytesIO()
    cv = Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    cv.setTitle(f'{account.name} · Buying thesis')
    cv.setAuthor('Lunartree')
    cv.setSubject('BioLens pipeline tracker: buying thesis report')

    pages = [(account.name, build_cover, True)] + [(title, b, False) for title, b in sections]
    for i, (title, builder, cover) in enumerate(pages, 1):
        _chrome(cv, None, account.name, title, i, total, cover)
        c = _fit(builder, account, ctx)
        flow, _ = _compose(builder, account, ctx, c)
        top = PAGE_H - MARGIN - (8 if cover else HEAD_H)
        frame = Frame(MARGIN, FOOT_H + 8, FRAME_W, top - FOOT_H - 8, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, showBoundary=0)
        frame.addFromList(flow, cv)
        if flow:
            raise RuntimeError(f'PDF section "{title}" does not fit one page')
        cv.showPage()
    cv.save()
    return buf.getvalue()
