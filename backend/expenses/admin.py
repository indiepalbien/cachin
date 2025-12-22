from django.contrib import admin
from .models import (
	Category, Project, Payee, Source, Exchange, Balance, Transaction,
	UserEmailConfig, UserEmailMessage, SplitwiseAccount, PendingTransaction,
	DefaultExchangeRate, CategorizationRule, UserProfile,
)

# Register finance models
admin.site.register(Category)
admin.site.register(Project)
admin.site.register(Payee)
admin.site.register(Source)
admin.site.register(Exchange)
admin.site.register(Balance)
admin.site.register(Transaction)
admin.site.register(DefaultExchangeRate)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
	list_display = ("user", "onboarding_step")
	search_fields = ("user__username",)
	list_filter = ("onboarding_step",)


@admin.register(UserEmailConfig)
class UserEmailConfigAdmin(admin.ModelAdmin):
	list_display = ("user", "full_address", "forwarding_email", "active", "created_at")
	search_fields = ("user__username", "user__email", "full_address", "forwarding_email", "alias_localpart")
	list_filter = ("active", "created_at")
	readonly_fields = ("created_at", "full_address")
	fields = ("user", "alias_localpart", "domain", "full_address", "forwarding_email", "active", "created_at")


@admin.register(UserEmailMessage)
class UserEmailMessageAdmin(admin.ModelAdmin):
	list_display = ("user", "subject", "from_address", "date", "downloaded_at")
	search_fields = ("user__username", "subject", "from_address", "to_addresses", "message_id")
	list_filter = ("user", "date")


@admin.register(SplitwiseAccount)
class SplitwiseAccountAdmin(admin.ModelAdmin):
	list_display = ("user", "splitwise_user_id", "last_synced")
	search_fields = ("user__username", "splitwise_user_id")
	readonly_fields = ("last_synced",)


@admin.register(PendingTransaction)
class PendingTransactionAdmin(admin.ModelAdmin):
	list_display = ("user", "external_id", "reason", "created_at")
	search_fields = ("user__username", "external_id")
	list_filter = ("user", "reason", "created_at")
	readonly_fields = ("created_at",)


@admin.register(CategorizationRule)
class CategorizationRuleAdmin(admin.ModelAdmin):
	list_display = ("user", "description_tokens", "category", "payee", "usage_count", "accuracy", "created_at")
	search_fields = ("user__username", "description_tokens")
	list_filter = ("user", "category", "payee", "created_at")
	readonly_fields = ("usage_count", "created_at", "updated_at")
	fieldsets = (
		("Rule Definition", {
			"fields": ("user", "description_tokens", "amount", "currency")
		}),
		("Predictions", {
			"fields": ("category", "payee")
		}),
		("Metadata", {
			"fields": ("usage_count", "accuracy", "created_at", "updated_at")
		}),
	)