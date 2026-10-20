from django import template

register = template.Library()


@register.filter
def bullets(value):
    """Split a textarea into non-empty lines for rendering as list items."""
    return [line.strip().lstrip('-•').strip() for line in (value or '').splitlines() if line.strip()]
