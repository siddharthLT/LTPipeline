import datetime

from .models import Task


def pending_actions(request):
    """Every open next action across all accounts, for the right-hand panel."""
    if not request.user.is_authenticated:
        return {}
    return {
        'pending_actions': list(Task.objects.filter(done=False).select_related('account')),
        'today_date': datetime.date.today(),
    }
