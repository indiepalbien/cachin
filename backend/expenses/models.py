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


class DefaultExchangeRate(models.Model):
    """Default exchange rates fetched from openexchangerates.org, updated weekly."""
    currency = models.CharField(max_length=3, unique=True, db_index=True)
    rate = models.DecimalField(max_digits=20, decimal_places=8)  # rate per 1 USD
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["currency"]

    def __str__(self):
        return f"{self.currency}: {self.rate} per USD (updated {self.last_updated})"


class Exchange(models.Model):
    """Exchange rate record: rate = target_currency per 1 source_currency."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    date = models.DateField()
    source_currency = models.CharField(max_length=3)
    target_currency = models.CharField(max_length=3)
    rate = models.DecimalField(max_digits=20, decimal_places=8)

    class Meta:
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["user", "source_currency", "target_currency", "date"], name="ex_user_src_tgt_date"),
        ]

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
        # Personal email address used when forwarding invoices
        forwarding_email = models.EmailField(
            blank=True,
            null=True,
            unique=True,
            help_text="Personal email address used when forwarding invoices"
        )

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
    amount_usd = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, 
                                     help_text="Pre-calculated USD amount for performance")
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

    class Meta:
        indexes = [
            models.Index(fields=["user", "date", "id"], name="tx_user_date_id"),
        ]

    def save(self, *args, **kwargs):
        """Override save to pre-calculate amount_usd."""
        # Only recalculate if amount_usd is not being explicitly set
        update_fields = kwargs.get('update_fields')
        if update_fields is None or 'amount_usd' not in update_fields:
            # Calculate USD amount before saving
            self.amount_usd = self._calculate_usd()
        super().save(*args, **kwargs)

    def _calculate_usd(self):
        """Calculate USD amount using exchange rates."""
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

    def to_usd(self, recalculate=False):
        """Return amount converted to USD.

        Uses pre-calculated amount_usd if available, unless recalculate=True.
        If amount_usd is None, calculates and saves it.

        Args:
            recalculate: Force recalculation even if cached value exists

        Returns:
            Decimal or None if no rate found.
        """
        # If we have cached value and not forcing recalculation, use it
        if self.amount_usd is not None and not recalculate:
            return self.amount_usd

        # Calculate new value
        calculated = self._calculate_usd()

        # Save to database for future use
        if calculated is not None:
            self.amount_usd = calculated
            self.save(update_fields=['amount_usd'])

        return calculated


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


class UserPreferences(models.Model):
    """User preferences for the expense tracking app."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='preferences')
    convert_expenses_to_usd = models.BooleanField(
        default=False,
        help_text="Convert category expenses to USD in reports"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Preferences"
        verbose_name_plural = "User Preferences"

    def __str__(self):
        return f"Preferences for {self.user.username}"


class CategorizationRule(models.Model):
    """
    Smart rule-based categorization system.
    
    When a user categorizes a transaction, rules are created based on:
    - Description tokens (sanitized, excluding generic words)
    - Amount and currency combinations
    - Category and payee assignments
    
    Rules are applied automatically to uncategorized transactions.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    
    # Rule components
    description_tokens = models.CharField(
        max_length=500,
        help_text="Space-separated tokens from transaction description"
    )
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Specific amount if part of the rule"
    )
    currency = models.CharField(
        max_length=3,
        null=True,
        blank=True,
        help_text="Currency code (e.g., USD, UYU)"
    )
    
    # Predictions
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    payee = models.ForeignKey(
        Payee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    # Metadata
    usage_count = models.IntegerField(default=0, help_text="Times this rule has been used")
    accuracy = models.FloatField(
        default=1.0,
        help_text="Accuracy score (0-1) based on matching transactions"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ["-usage_count", "-created_at"]
        indexes = [
            models.Index(fields=["user", "description_tokens"], name="rule_user_tokens"),
            models.Index(fields=["user", "created_at"], name="rule_user_created"),
        ]
    
    def __str__(self):
        rule_parts = [self.description_tokens]
        if self.amount:
            rule_parts.append(f"{self.amount}")
        if self.currency:
            rule_parts.append(self.currency)
        return f"Rule: {' + '.join(rule_parts)} → {self.category or self.payee or 'uncategorized'}"
    
    def increment_usage(self):
        """Increment usage counter."""
        self.usage_count += 1
        self.save(update_fields=['usage_count', 'updated_at'])