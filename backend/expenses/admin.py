from django.contrib import admin
from .models import (
	Category, Project, Payee, Source, Exchange, Balance, Transaction,
	UserEmailConfig, UserEmailMessage,
)

# Register finance models
admin.site.register(Category)
admin.site.register(Project)
admin.site.register(Payee)
admin.site.register(Source)
admin.site.register(Exchange)
admin.site.register(Balance)
admin.site.register(Transaction)


@admin.register(UserEmailConfig)
class UserEmailConfigAdmin(admin.ModelAdmin):
	list_display = ("user", "full_address", "active", "created_at")
	search_fields = ("user__username", "full_address", "alias_localpart")


@admin.register(UserEmailMessage)
class UserEmailMessageAdmin(admin.ModelAdmin):
	list_display = ("user", "subject", "from_address", "date", "downloaded_at")
	search_fields = ("user__username", "subject", "from_address", "to_addresses", "message_id")
	list_filter = ("user", "date")