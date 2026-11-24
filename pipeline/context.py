import datetime

from django.conf import settings

from .models import Task


def app_mode(request):
    """Which half of the product this deployment serves, for the sidebar and the login page."""
    mode = settings.APP_MODE
    return {'app_mode': mode, 'show_pipeline': mode != 'usage', 'show_usage': mode != 'pipeline', 'usage_only': mode == 'usage',
            'pipeline_url': settings.PIPELINE_URL, 'usage_url': settings.USAGE_URL}


def pending_actions(request):
    """Every open next action across all accounts, for the right-hand panel."""
    if settings.APP_MODE == 'usage' or not request.user.is_authenticated:
        return {}
    return {
        'pending_actions': list(Task.objects.filter(done=False).select_related('account')),
        'today_date': datetime.date.today(),
    }
