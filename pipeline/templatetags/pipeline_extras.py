from django import template
from django.conf import settings
from django.urls import NoReverseMatch, reverse

register = template.Library()


@register.filter
def bullets(value):
    """Split a textarea into non-empty lines for rendering as list items."""
    return [line.strip().lstrip('-•').strip() for line in (value or '').splitlines() if line.strip()]


@register.filter
def clock(seconds):
    """1:05, 12:40, 1:02:09, or 47h 18m for a recording left open for days."""
    s = int(seconds or 0)
    if s >= 86400:
        return '%dh %02dm' % (s // 3600, s % 3600 // 60)
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return '%d:%02d:%02d' % (h, m, sec) if h else '%d:%02d' % (m, sec)


@register.filter
def spent(seconds):
    """Time spent as 45s, 12 min, 3h 05m."""
    s = int(seconds or 0)
    if s < 90:
        return '%ds' % s
    if s < 5400:
        return '%d min' % round(s / 60)
    return '%dh %02dm' % (s // 3600, s % 3600 // 60)


@register.filter
def ago(when):
    """Compact age: 5m ago, 3h ago, 12d ago."""
    from django.utils import timezone
    secs = max(0, int((timezone.now() - when).total_seconds()))
    if secs < 3600:
        return '%dm ago' % max(1, secs // 60)
    if secs < 86400:
        return '%dh ago' % (secs // 3600)
    return '%dd ago' % (secs // 86400)


@register.simple_tag
def account_url(pk):
    """An account's page. Product usage deployed on its own has no account pages, so it links to the pipeline deployment."""
    try:
        return reverse('pipeline:account_detail', args=[pk])
    except NoReverseMatch:
        return '%s/accounts/%s/' % (settings.PIPELINE_URL, pk) if settings.PIPELINE_URL else '#'
