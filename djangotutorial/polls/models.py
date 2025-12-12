from django.db import models
from django.contrib import admin


# Create your models here.
from django.db import models
from django.utils import timezone
import datetime
from django.conf import settings
from decimal import Decimal


class Question(models.Model):
    question_text = models.CharField(max_length=200)
    pub_date = models.DateTimeField("date published")
    def __str__(self):
        return self.question_text

    @admin.display(
        boolean=True,
        ordering="pub_date",
        description="Published recently?",
    )
    def was_published_recently(self):
        now = timezone.now()
        return now - datetime.timedelta(days=1) <= self.pub_date <= now

class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    choice_text = models.CharField(max_length=200)
    votes = models.IntegerField(default=0)
    def __str__(self):
        return self.choice_text


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