"""ARR forecast for the dashboard: when each account is predicted to sign, weighted by its score."""
import calendar
import datetime
import re

from .stages import STAGE_DAYS, STAGE_WEIGHTS

DEFAULT_ARR = 15000   # lowest tier, used when an account has no deal value yet
USER_PRICE = 2000     # assumed yearly price per user, to turn ARR into an expected user count
MONTHS = 12
COLD_CYCLE_DAYS = sum(STAGE_DAYS.values())          # the date formula's span for a cold account (135 days)
FIRST_CALL_SCORE = sum(STAGE_WEIGHTS[n] for n in (1, 2, 3))   # score of an account that has just had its first call
DEFAULT_CYCLE_MONTHS = 3        # typical cold account; 6 when being conservative
DEFAULT_CONVERSION = 0.20       # chance an account that has had a first call signs


def parse_arr(text):
    """'$30K' -> 30000, '$12-25K' -> 18500 (midpoint), '$1.2M' -> 1200000. None when no number."""
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?))?\s*([kKmM])?', text or '')
    if not m:
        return None
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) else lo
    mult = {'k': 1_000, 'm': 1_000_000}.get((m.group(3) or '').lower(), 1)
    value = (lo + hi) / 2 * mult
    if not m.group(3) and value < 1000:   # '$30' with no suffix is almost certainly $30K
        value *= 1000
    return round(value)


def add_months(day, n):
    month = day.month - 1 + n
    year = day.year + month // 12
    month = month % 12 + 1
    return datetime.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def close_probability(score, conversion):
    """Chance an account signs. `conversion` at the first call, rising to 100% at contract.

    Before the first call it scales down in proportion (a 5% account is a third of the way there).
    """
    if score >= FIRST_CALL_SCORE:
        return conversion + (1 - conversion) * (score - FIRST_CALL_SCORE) / (100 - FIRST_CALL_SCORE)
    return conversion * score / FIRST_CALL_SCORE


def build(accounts, today=None, cycle_months=DEFAULT_CYCLE_MONTHS, conversion=DEFAULT_CONVERSION):
    """accounts need .name, .score, .deal_value and .contract_info (done/date). Returns 13 points, month 0..12.

    This only reshapes the graph. Scores and the dashboard dates are not changed.
    - Timing: the date formula says a cold account signs in about 135 days; the graph stretches or squeezes
      every account's remaining time so a cold account takes `cycle_months` instead.
    - Likelihood: close_probability(). Expected signings are whole accounts: the summed likelihood of every
      account due by a date, rounded; the accounts counted are the most likely ones, and their deal values
      make the ARR. The set only grows month to month, so ARR never goes down.
    """
    today = today or datetime.date.today()
    factor = cycle_months * 30.4 / COLD_CYCLE_DAYS
    deals = []
    for a in accounts:
        info = a.contract_info
        due = today if info['done'] else today + datetime.timedelta(days=round(max((info['date'] - today).days, 0) * factor))
        deals.append({'name': a.name, 'date': due, 'p': 1.0 if info['done'] else close_probability(a.score, conversion),
                      'arr': parse_arr(a.deal_value) or DEFAULT_ARR})
    points, chosen = [], []
    for m in range(MONTHS + 1):
        cutoff = add_months(today, m)
        hit = [d for d in deals if d['date'] <= cutoff]
        extra = int(sum(d['p'] for d in hit) + 0.5) - len(chosen)
        if extra > 0:
            rest = sorted((d for d in hit if d not in chosen), key=lambda d: (-d['p'], d['date'], d['name']))
            chosen += rest[:extra]
        arr = sum(d['arr'] for d in chosen)
        best = sum(d['arr'] for d in hit)
        points.append({
            'month': m, 'date': cutoff.strftime('%b %-d, %Y'),
            'accounts': len(chosen), 'arr': arr, 'users': round(arr / USER_PRICE),
            'names': [d['name'] for d in chosen],
            'best_accounts': len(hit), 'best_arr': best, 'best_users': round(best / USER_PRICE),
        })
    return {'points': points, 'user_price': USER_PRICE, 'total': len(deals),
            'cycle_months': cycle_months, 'conversion': round(conversion * 100)}
