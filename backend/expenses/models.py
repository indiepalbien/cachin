from django.db import models
from django.utils import timezone
import datetime
from django.conf import settings
from decimal import Decimal


class Category(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=150)

    def __str__(self):
        return self.name


class Project(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=150)

    def __str__(self):
        return self.name


class Payee(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)

    def __str__(self):
        return self.name


class Source(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)

    def __str__(self):
        return self.name


class Exchange(models.Model):
    """Exchange rate record: rate = target_currency per 1 source_currency."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    date = models.DateField()
    source_currency = models.CharField(max_length=3)
    target_currency = models.CharField(max_length=3)
    rate = models.DecimalField(max_digits=20, decimal_places=8)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date} {self.source_currency}->{self.target_currency} @ {self.rate}"


 
# Email processing models
class UserEmailConfig(models.Model):
        """Per-user email automation config.

        Stores the unique alias assigned to each user, e.g.
        <random>.automation@cachinapp.com, and optional mailbox credentials
        if needed per-user.
        """
        user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
        alias_localpart = models.CharField(max_length=64, unique=True)
        domain = models.CharField(max_length=255, default="cachinapp.com")
        full_address = models.EmailField(unique=True)
        # Optional per-user mailbox credentials (can be blank if using a shared ingest mailbox)
        mailbox_username = models.CharField(max_length=255, blank=True)
        mailbox_password = models.CharField(max_length=255, blank=True)
        active = models.BooleanField(default=True)
        created_at = models.DateTimeField(auto_now_add=True)

        class Meta:
            verbose_name = "User Email Config"
            verbose_name_plural = "User Email Configs"

        def save(self, *args, **kwargs):
            # Address format: automation.<random>@domain
            self.full_address = f"automation.{self.alias_localpart}@{self.domain}".lower()
            super().save(*args, **kwargs)

        def __str__(self):
            return f"{self.user} -> {self.full_address}"


class UserEmailMessage(models.Model):
    """Stored email messages associated to a user."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message_id = models.CharField(max_length=255, db_index=True)
    subject = models.CharField(max_length=500, blank=True)
    from_address = models.CharField(max_length=500, blank=True)
    to_addresses = models.TextField(blank=True)  # comma-separated
    date = models.DateTimeField(null=True, blank=True)
    raw_eml = models.BinaryField()  # store the raw RFC822 bytes
    downloaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True)

    class Meta:
        unique_together = ("user", "message_id")
        ordering = ["-downloaded_at"]

    def __str__(self):
        return f"{self.user} - {self.subject or self.message_id}"

class Balance(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    source = models.ForeignKey(Source, on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3)
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    def __str__(self):
        return f"{self.source.name}: {self.amount} {self.currency} ({self.start_date} - {self.end_date})"


class Transaction(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    date = models.DateField()
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    source = models.ForeignKey(Source, on_delete=models.SET_NULL, null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True)
    comments = models.TextField(blank=True)
    payee = models.ForeignKey(Payee, on_delete=models.SET_NULL, null=True, blank=True)
    external_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    status = models.CharField(
        max_length=32,
        choices=(
            ("confirmed", "Confirmed"),
            ("pending_duplicate", "Pending duplicate"),
        ),
        default="confirmed",
    )

    def __str__(self):
        return f"{self.date} {self.amount} {self.currency}"

    def to_usd(self):
        """Return amount converted to USD using the most recent Exchange for this user.

        Returns Decimal or None if no rate found.
        """
        if self.currency.upper() == 'USD':
            return self.amount

        # Try direct rate: source_currency -> USD
        rate_qs = Exchange.objects.filter(
            user=self.user,
            source_currency__iexact=self.currency,
            target_currency__iexact='USD',
            date__lte=self.date,
        ).order_by('-date')
        if rate_qs.exists():
            rate = rate_qs.first().rate
            try:
                return (self.amount * rate).quantize(Decimal('0.01'))
            except Exception:
                return None

        # Try inverse rate: USD -> source_currency, then divide
        inv_qs = Exchange.objects.filter(
            user=self.user,
            source_currency__iexact='USD',
            target_currency__iexact=self.currency,
            date__lte=self.date,
        ).order_by('-date')
        if inv_qs.exists():
            inv_rate = inv_qs.first().rate
            try:
                if inv_rate and inv_rate != 0:
                    return (self.amount / inv_rate).quantize(Decimal('0.01'))
            except Exception:
                return None

        return None


class PendingTransaction(models.Model):
    """Queue of transactions that could not be auto-inserted (e.g., duplicates)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    external_id = models.CharField(max_length=255, db_index=True)
    payload = models.JSONField()  # parsed fields (description, amount, currency, source, etc.)
    reason = models.CharField(max_length=64, default="duplicate")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]



class SplitwiseAccount(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='splitwise')
    oauth_token = models.CharField(max_length=255, blank=True, null=True)
    oauth_token_secret = models.CharField(max_length=255, blank=True, null=True)
    splitwise_user_id = models.CharField(max_length=64, blank=True, null=True)
    last_synced = models.DateTimeField(null=True, blank=True)
    raw = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"SplitwiseAccount({self.user_id})"