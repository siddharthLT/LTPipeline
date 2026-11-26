from django.contrib import admin, messages

from .models import Account, DigestRecipient

admin.site.register(Account)


@admin.register(DigestRecipient)
class DigestRecipientAdmin(admin.ModelAdmin):
    """Who gets the pipeline digest. Tick Active for the people who should receive it; the action below sends it right now."""
    list_display = ('email', 'name', 'active', 'created_at')
    list_editable = ('active', 'name')
    list_filter = ('active',)
    search_fields = ('email', 'name')
    actions = ['send_now', 'activate', 'deactivate']

    @admin.action(description='Send the digest now to the selected people')
    def send_now(self, request, queryset):
        from .digest_email import send_digest
        for email, result in send_digest([r.email for r in queryset]):
            if result.startswith('ERROR'):
                self.message_user(request, '%s: %s' % (email, result), messages.ERROR)
            else:
                self.message_user(request, 'Sent to %s' % email, messages.SUCCESS)

    @admin.action(description='Mark selected as active (they will get the digest)')
    def activate(self, request, queryset):
        self.message_user(request, '%d activated' % queryset.update(active=True))

    @admin.action(description='Mark selected as inactive (stop sending)')
    def deactivate(self, request, queryset):
        self.message_user(request, '%d deactivated' % queryset.update(active=False))
