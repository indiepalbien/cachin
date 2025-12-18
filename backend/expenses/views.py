# Create your views here.
from django.http import HttpResponse, HttpResponseRedirect, Http404, JsonResponse
from django.template import loader
from django.shortcuts import get_object_or_404, render, redirect
from django.views import generic
from django.urls import reverse
from django.conf import settings
from django.db.models import F, Q, OuterRef, Subquery, Value, DecimalField, ExpressionWrapper, Case, When, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from urllib.parse import quote_plus
from .models import Category, Project, Payee, Source, Exchange, Balance, Transaction, UserEmailMessage, UserEmailConfig, PendingTransaction, SplitwiseAccount, DefaultExchangeRate, UserPreferences
from . import forms
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone as dj_timezone
from decimal import Decimal, InvalidOperation
import datetime
import requests
from requests_oauthlib import OAuth1Session
from django.core.paginator import Paginator
import logging

logger = logging.getLogger(__name__)


def get_exchange_rate(user, source_currency, target_currency, date):
    """
    Get exchange rate from source_currency to target_currency.
    
    First tries user-specified rates (Exchange model), then falls back to default rates.
    Returns Decimal or None if not found.
    """
    if source_currency.upper() == target_currency.upper():
        return Decimal('1')
    
    # Try user-specified rate first
    user_rate_qs = Exchange.objects.filter(
        user=user,
        source_currency__iexact=source_currency,
        target_currency__iexact=target_currency,
        date__lte=date,
    ).order_by('-date')
    
    if user_rate_qs.exists():
        return user_rate_qs.first().rate
    
    # Fall back to default rates
    # For now, assume target_currency is USD
    try:
        source_rate = DefaultExchangeRate.objects.get(currency__iexact=source_currency)
        target_rate = DefaultExchangeRate.objects.get(currency__iexact=target_currency)
        
        if target_rate.rate != 0:
            return source_rate.rate / target_rate.rate
    except DefaultExchangeRate.DoesNotExist:
        pass
    
    return None

@login_required
@require_POST
def quick_transaction(request):
    """Handle small inline form to create a Transaction quickly.

    Behavior:
    - Required: description, amount, date, currency.
    - Shows existing DB options in the form (via datalist); on submit, missing related objects are created for the user (cascade).
    - Returns JSON when request is AJAX/JSON (used by inline JS) or redirects with messages for normal POST.
    """
    user = request.user
    data = request.POST

    # Required fields
    description = (data.get("description") or "").strip()
    amount = data.get("amount")
    date_str = data.get("date")
    currency = (data.get("currency") or "").upper().strip()

    # Optional fields: category, project, payee, source
    def get_or_create_model(model, name):
        if not name:
            return None
        obj = model.objects.filter(user=user, name__iexact=name.strip()).first()
        if obj:
            return obj
        return model.objects.create(user=user, name=name.strip())

    category_name = data.get("category")
    project_name = data.get("project")
    payee_name = data.get("payee")
    source_name = data.get("source")

    # Validate required fields
    errors = []
    if not description:
        errors.append("Descripción requerida.")
    if not amount:
        errors.append("Amount is required.")
    if not date_str:
        errors.append("Date is required.")
    if not currency:
        errors.append("Currency is required.")

    # Validate currency format (ISO-4217 style: 3 letters)
    if currency and (len(currency) != 3 or not currency.isalpha()):
        errors.append("Currency must be a 3-letter code (ISO-4217).")

    # If any errors, respond appropriately
    if errors:
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.META.get("HTTP_ACCEPT", "").find("application/json") != -1:
            return JsonResponse({"success": False, "errors": errors}, status=400)
        for e in errors:
            messages.error(request, e)
        return redirect("profile")

    # Parse amount and date
    try:
        amount_dec = Decimal(amount)
    except (InvalidOperation, TypeError):
        msg = "Amount must be a number."
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "errors": [msg]}, status=400)
        messages.error(request, msg)
        return redirect("profile")

    try:
        tx_date = datetime.date.fromisoformat(date_str)
    except Exception:
        msg = "Invalid date format. Use YYYY-MM-DD."
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "errors": [msg]}, status=400)
        messages.error(request, msg)
        return redirect("profile")

    # Create or get related objects (cascade)
    category = get_or_create_model(Category, category_name)
    project = get_or_create_model(Project, project_name)
    payee = get_or_create_model(Payee, payee_name)
    source = get_or_create_model(Source, source_name)

    comments = data.get("comments", "")

    try:
        tx = Transaction.objects.create(
            user=user,
            date=tx_date,
            description=description,
            amount=amount_dec,
            currency=currency,
            source=source,
            category=category,
            project=project,
            payee=payee,
            comments=comments,
        )
        success_msg = "Transacción añadida."
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.META.get("HTTP_ACCEPT", "").find("application/json") != -1:
            return JsonResponse({"success": True, "message": success_msg, "id": tx.id})
        messages.success(request, success_msg)
    except Exception as e:
        err = f"Error creando transacción: {e}"
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "errors": [err]}, status=500)
        messages.error(request, err)

    return redirect("profile")


@login_required
@require_GET
def suggest(request, kind):
    """Return a JSON list of existing names for `kind`.

    `kind` is one of: category, project, payee
    Query param `q` filters by prefix (case-insensitive).
    Only returns existing DB entries (does not create).
    """
    q = request.GET.get("q", "").strip()
    mapping = {
        "category": Category,
        "project": Project,
        "payee": Payee,
        "source": Source,
    }
    Model = mapping.get(kind)
    if not Model:
        return JsonResponse({"results": []})
    qs = Model.objects.filter(user=request.user)
    if q:
        qs = qs.filter(name__istartswith=q)
    names = list(qs.order_by("name").values_list("name", flat=True)[:25])
    return JsonResponse({"results": names})


@login_required
def manage_dashboard(request):
    """Simple management dashboard with links to each resource."""
    resources = [
        ("Categorizar transacciones", "expenses:categorize_transactions"),
        ("Categories", "expenses:manage_categories"),
        ("Projects", "expenses:manage_projects"),
        ("Payees", "expenses:manage_payees"),
        ("Sources", "expenses:manage_sources"),
        ("Exchanges", "expenses:manage_exchanges"),
        ("Balances", "expenses:manage_balances"),
        ("Transactions", "expenses:manage_transactions"),
        ("Splitwise", "expenses:splitwise_status"),
        ("Emails", "expenses:manage_emails"),
        ("Pending", "expenses:manage_pending_transactions"),
    ]
    return render(request, "manage/dashboard.html", {"resources": resources})


def _update_transaction_category(request, user):
    """Helper to update transaction category/comments. Returns (success, message, tx_id)."""
    tx_id = request.POST.get("tx_id")
    category_id = request.POST.get("category_id")
    comments = (request.POST.get("comments") or "").strip()

    if not tx_id:
        return (False, "ID de transacción requerido.", None)

    try:
        tx = Transaction.objects.get(pk=tx_id, user=user)
    except Transaction.DoesNotExist:
        return (False, "Transacción no encontrada.", None)

    category = None
    if category_id:
        try:
            category = Category.objects.get(pk=category_id, user=user)
        except Category.DoesNotExist:
            return (False, "Categoría no encontrada.", None)

    tx.category = category
    tx.comments = comments
    tx.save(update_fields=["category", "comments"])

    return (True, f"Transacción '{tx.description}' actualizada.", tx.id)


@login_required
def categorize_transactions(request):
    """View to add categories and assign them to uncategorized transactions in one place."""
    user = request.user

    if request.method == "POST":
        action = request.POST.get("action") or ""

        if action == "add_category":
            name = (request.POST.get("name") or "").strip()
            if not name:
                messages.error(request, "El nombre de la categoría es obligatorio.")
                return redirect("expenses:categorize_transactions")

            cat, created = Category.objects.get_or_create(user=user, name=name)
            if created:
                messages.success(request, f"Categoría '{cat.name}' creada.")
            else:
                messages.info(request, f"Ya existe la categoría '{cat.name}'.")
            return redirect("expenses:categorize_transactions")

        if action == "assign_tx":
            success, message, tx_id = _update_transaction_category(request, user)

            # AJAX response
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                if success:
                    return JsonResponse({
                        "success": True,
                        "message": message,
                        "tx_id": tx_id
                    })
                else:
                    return JsonResponse({
                        "success": False,
                        "errors": [message]
                    }, status=400)

            # Traditional POST response (fallback)
            if success:
                messages.success(request, message)
                return redirect(reverse("expenses:categorize_transactions") + f"#tx-{tx_id}")
            else:
                messages.error(request, message)
                return redirect("expenses:categorize_transactions")

        messages.error(request, "Acción no reconocida.")
        return redirect("expenses:categorize_transactions")

    categories = Category.objects.filter(user=user).order_by("name")
    uncategorized_qs = (
        Transaction.objects.filter(user=user, category__isnull=True)
        .select_related("source", "project", "payee")
        .order_by("-date", "-id")
    )

    page_number = request.GET.get("page") or 1
    paginator = Paginator(uncategorized_qs, 25)
    tx_page = paginator.get_page(page_number)

    context = {
        "categories": categories,
        "tx_page": tx_page,
    }
    return render(request, "manage/categorize.html", context)


@login_required
def edit_category_transactions(request):
    """View to edit transactions filtered by category and optionally currency/month."""
    user = request.user

    # Handle POST requests first (for AJAX saves)
    if request.method == "POST":
        action = request.POST.get("action") or ""

        if action == "assign_tx":
            success, message, tx_id = _update_transaction_category(request, user)

            # AJAX response
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                if success:
                    return JsonResponse({
                        "success": True,
                        "message": message,
                        "tx_id": tx_id
                    })
                else:
                    return JsonResponse({
                        "success": False,
                        "errors": [message]
                    }, status=400)

            # Traditional POST response (fallback) - redirect with filters
            category_name = request.GET.get('category', '')
            currency = request.GET.get('currency', '')
            month_param = request.GET.get('month', '')

            if success:
                messages.success(request, message)
            else:
                messages.error(request, message)

            # Redirect back with same filters if available
            if category_name:
                params = f"?category={category_name}"
                if currency:
                    params += f"&currency={currency}"
                if month_param:
                    params += f"&month={month_param}"
                return redirect(reverse("expenses:edit_category_transactions") + params)
            else:
                return redirect("profile")

        if action == "delete_tx":
            tx_id = request.POST.get("tx_id")

            if not tx_id:
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({"success": False, "errors": ["ID de transacción requerido"]}, status=400)
                messages.error(request, "ID de transacción requerido.")
                return redirect("profile")

            try:
                tx = Transaction.objects.get(pk=tx_id, user=user)
                tx_description = tx.description
                tx.delete()

                # AJAX response
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({
                        "success": True,
                        "message": f"Transacción '{tx_description}' eliminada.",
                        "tx_id": tx_id
                    })

                messages.success(request, f"Transacción '{tx_description}' eliminada.")
            except Transaction.DoesNotExist:
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({"success": False, "errors": ["Transacción no encontrada"]}, status=404)
                messages.error(request, "Transacción no encontrada.")

            # Redirect back with filters
            category_name = request.GET.get('category', '')
            currency = request.GET.get('currency', '')
            month_param = request.GET.get('month', '')

            if category_name:
                params = f"?category={category_name}"
                if currency:
                    params += f"&currency={currency}"
                if month_param:
                    params += f"&month={month_param}"
                return redirect(reverse("expenses:edit_category_transactions") + params)
            else:
                return redirect("profile")

        messages.error(request, "Acción no reconocida.")
        return redirect("profile")

    # GET request - show filtered transactions
    category_name = request.GET.get('category', '')
    source_name = request.GET.get('source', '')
    project_name = request.GET.get('project', '')
    currency = request.GET.get('currency', '')
    month_param = request.GET.get('month', '')  # Format: YYYY-MM

    # Need at least one filter (category, source, or project)
    if not category_name and not source_name and not project_name:
        messages.error(request, "Se requiere al menos un filtro (categoría, origen o proyecto).")
        return redirect("profile")

    # Start with base queryset
    transactions_qs = Transaction.objects.filter(user=user)

    # Apply category filter if provided
    if category_name:
        if category_name == 'Sin categoría':
            transactions_qs = transactions_qs.filter(category__isnull=True)
        else:
            try:
                category = Category.objects.get(user=user, name=category_name)
                transactions_qs = transactions_qs.filter(category=category)
            except Category.DoesNotExist:
                messages.error(request, f"Categoría '{category_name}' no encontrada.")
                return redirect("profile")

    # Apply source filter if provided
    if source_name:
        try:
            source = Source.objects.get(user=user, name=source_name)
            transactions_qs = transactions_qs.filter(source=source)
        except Source.DoesNotExist:
            messages.error(request, f"Origen '{source_name}' no encontrado.")
            return redirect("profile")

    # Apply project filter if provided
    if project_name:
        try:
            project = Project.objects.get(user=user, name=project_name)
            transactions_qs = transactions_qs.filter(project=project)
        except Project.DoesNotExist:
            messages.error(request, f"Proyecto '{project_name}' no encontrado.")
            return redirect("profile")

    # Apply currency filter if provided
    if currency:
        transactions_qs = transactions_qs.filter(currency=currency)

    # Apply month filter if provided
    if month_param:
        try:
            year, month = map(int, month_param.split('-'))
            import calendar
            last_day = calendar.monthrange(year, month)[1]
            start_date = datetime.date(year, month, 1)
            end_date = datetime.date(year, month, last_day)
            transactions_qs = transactions_qs.filter(date__gte=start_date, date__lte=end_date)
        except (ValueError, AttributeError):
            pass  # Invalid month format, skip filter

    transactions_qs = transactions_qs.select_related("source", "project", "payee", "category").order_by("-date", "-id")

    # Pagination
    page_number = request.GET.get("page") or 1
    paginator = Paginator(transactions_qs, 25)
    tx_page = paginator.get_page(page_number)

    # Get all categories for the dropdown
    categories = Category.objects.filter(user=user).order_by("name")

    # Build filter description for display
    filter_parts = []
    if category_name:
        filter_parts.append(f"Categoría: {category_name}")
    if source_name:
        filter_parts.append(f"Origen: {source_name}")
    if project_name:
        filter_parts.append(f"Proyecto: {project_name}")
    if currency:
        filter_parts.append(f"Moneda: {currency}")
    if month_param:
        filter_parts.append(f"Mes: {month_param}")

    filter_desc = " | ".join(filter_parts)

    context = {
        "categories": categories,
        "tx_page": tx_page,
        "category_name": category_name,
        "source_name": source_name,
        "project_name": project_name,
        "currency": currency,
        "month_param": month_param,
        "filter_desc": filter_desc,
    }
    return render(request, "manage/edit_category_transactions.html", context)


class OwnerRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        obj = self.get_object()
        return obj.user == self.request.user


class OwnerListView(LoginRequiredMixin, ListView):
    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(user=self.request.user)
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        model_name = self.model._meta.model_name
        plural_map = {
            "category": "categories",
            "project": "projects",
            "payee": "payees",
            "source": "sources",
            "exchange": "exchanges",
            "balance": "balances",
            "transaction": "transactions",
        }
        plural = plural_map.get(model_name, model_name + "s")
        ctx["create_url_name"] = f"expenses:manage_{model_name}_add"
        ctx["edit_url_name"] = f"expenses:manage_{model_name}_edit"
        ctx["delete_url_name"] = f"expenses:manage_{model_name}_delete"
        ctx["list_url"] = reverse(f"expenses:manage_{plural}") if plural else None
        # Provide a safe verbose name for templates (avoid accessing _meta from templates)
        ctx["model_verbose_name_plural"] = self.model._meta.verbose_name_plural
        try:
            ctx["back_url"] = reverse("profile")
        except Exception:
            ctx["back_url"] = None
        return ctx


class OwnerCreateView(LoginRequiredMixin, CreateView):
    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # provide a safe verbose name for templates
        ctx["model_verbose_name"] = self.model._meta.verbose_name
        model_name = self.model._meta.model_name
        plural_map = {
            "category": "categories",
            "project": "projects",
            "payee": "payees",
            "source": "sources",
            "exchange": "exchanges",
            "balance": "balances",
            "transaction": "transactions",
        }
        plural = plural_map.get(model_name, model_name + "s")
        ctx["list_url"] = reverse(f"expenses:manage_{plural}")
        ctx["back_url"] = ctx["list_url"]
        return ctx
    def get_success_url(self):
        return getattr(self, "success_url", None) or self.request.POST.get("next") or self.request.GET.get("next") or self.get_context_data().get("list_url") or super().get_success_url()


class OwnerUpdateView(LoginRequiredMixin, OwnerRequiredMixin, UpdateView):
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["model_verbose_name"] = self.model._meta.verbose_name
        model_name = self.model._meta.model_name
        plural_map = {
            "category": "categories",
            "project": "projects",
            "payee": "payees",
            "source": "sources",
            "exchange": "exchanges",
            "balance": "balances",
            "transaction": "transactions",
        }
        plural = plural_map.get(model_name, model_name + "s")
        ctx["list_url"] = reverse(f"expenses:manage_{plural}")
        ctx["back_url"] = ctx["list_url"]
        # Add delete URL for edit mode
        if self.object and self.object.pk:
            singular = model_name
            ctx["delete_url"] = reverse(f"expenses:manage_{singular}_delete", kwargs={"pk": self.object.pk})
        return ctx
    def get_success_url(self):
        return getattr(self, "success_url", None) or self.request.POST.get("next") or self.request.GET.get("next") or self.get_context_data().get("list_url") or super().get_success_url()


class OwnerDeleteView(LoginRequiredMixin, OwnerRequiredMixin, DeleteView):
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        model_name = self.model._meta.model_name
        plural_map = {
            "category": "categories",
            "project": "projects",
            "payee": "payees",
            "source": "sources",
            "exchange": "exchanges",
            "balance": "balances",
            "transaction": "transactions",
        }
        plural = plural_map.get(model_name, model_name + "s")
        list_url = reverse(f"expenses:manage_{plural}")
        ctx["list_url"] = list_url
        ctx["back_url"] = list_url
        ctx["model_verbose_name"] = self.model._meta.verbose_name
        return ctx

    def get_success_url(self):
        return self.get_context_data().get("list_url") or super().get_success_url()


# Category views
class CategoryListView(OwnerListView):
    model = Category
    template_name = "manage/list.html"


class CategoryCreateView(OwnerCreateView):
    model = Category
    fields = ["name"]
    template_name = "manage/form.html"
    success_url = reverse_lazy("expenses:manage_categories")


class CategoryUpdateView(OwnerUpdateView):
    model = Category
    fields = ["name"]
    template_name = "manage/form.html"
    success_url = reverse_lazy("expenses:manage_categories")


class CategoryDeleteView(OwnerDeleteView):
    model = Category
    template_name = "manage/confirm_delete.html"
    success_url = reverse_lazy("expenses:manage_categories")


# Project views
class ProjectListView(OwnerListView):
    model = Project
    template_name = "manage/list.html"


class ProjectCreateView(OwnerCreateView):
    model = Project
    fields = ["name"]
    template_name = "manage/form.html"
    success_url = reverse_lazy("expenses:manage_projects")


class ProjectUpdateView(OwnerUpdateView):
    model = Project
    fields = ["name"]
    template_name = "manage/form.html"
    success_url = reverse_lazy("expenses:manage_projects")


class ProjectDeleteView(OwnerDeleteView):
    model = Project
    template_name = "manage/confirm_delete.html"
    success_url = reverse_lazy("expenses:manage_projects")


# Payee views
class PayeeListView(OwnerListView):
    model = Payee
    template_name = "manage/list.html"


class PayeeCreateView(OwnerCreateView):
    model = Payee
    fields = ["name"]
    template_name = "manage/form.html"
    success_url = reverse_lazy("expenses:manage_payees")


class PayeeUpdateView(OwnerUpdateView):
    model = Payee
    fields = ["name"]
    template_name = "manage/form.html"
    success_url = reverse_lazy("expenses:manage_payees")


class PayeeDeleteView(OwnerDeleteView):
    model = Payee
    template_name = "manage/confirm_delete.html"
    success_url = reverse_lazy("expenses:manage_payees")


# Source views
class SourceListView(OwnerListView):
    model = Source
    template_name = "manage/list.html"


class SourceCreateView(OwnerCreateView):
    model = Source
    fields = ["name"]
    template_name = "manage/form.html"
    success_url = reverse_lazy("expenses:manage_sources")


class SourceUpdateView(OwnerUpdateView):
    model = Source
    fields = ["name"]
    template_name = "manage/form.html"
    success_url = reverse_lazy("expenses:manage_sources")


class SourceDeleteView(OwnerDeleteView):
    model = Source
    template_name = "manage/confirm_delete.html"
    success_url = reverse_lazy("expenses:manage_sources")


# Exchange views
class ExchangeListView(OwnerListView):
    model = Exchange
    template_name = "manage/list.html"


class ExchangeCreateView(OwnerCreateView):
    model = Exchange
    form_class = forms.ExchangeForm
    template_name = "manage/form.html"
    success_url = reverse_lazy("expenses:manage_exchanges")


class ExchangeUpdateView(OwnerUpdateView):
    model = Exchange
    form_class = forms.ExchangeForm
    template_name = "manage/form.html"
    success_url = reverse_lazy("expenses:manage_exchanges")


class ExchangeDeleteView(OwnerDeleteView):
    model = Exchange
    template_name = "manage/confirm_delete.html"
    success_url = reverse_lazy("expenses:manage_exchanges")


class EmailMessageListView(LoginRequiredMixin, ListView):
    model = UserEmailMessage
    template_name = "manage/list.html"

    def get_queryset(self):
        return UserEmailMessage.objects.filter(user=self.request.user).order_by('-downloaded_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['model_verbose_name'] = 'Emails'
        ctx['model_verbose_name_plural'] = 'Emails'
        # No create/edit/delete routes for email messages list (read-only)
        ctx['create_url_name'] = None
        ctx['edit_url_name'] = None
        ctx['delete_url_name'] = None
        # Show user's personalized email address (alias) if available
        cfg = UserEmailConfig.objects.filter(user=self.request.user, active=True).first()
        if cfg and cfg.full_address:
            ctx['header_note'] = f"Tu dirección de correo: {cfg.full_address}"
        else:
            ctx['header_note'] = "No tienes una dirección de correo configurada aún."
        # Pass email config to template for forwarding email form
        ctx['email_config'] = cfg
        return ctx


class PendingTransactionListView(LoginRequiredMixin, ListView):
    model = PendingTransaction
    template_name = "manage/list.html"

    def get_queryset(self):
        return PendingTransaction.objects.filter(user=self.request.user).order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['model_verbose_name'] = 'Pending'
        ctx['model_verbose_name_plural'] = 'Pending'
        ctx['create_url_name'] = None
        ctx['edit_url_name'] = None
        ctx['delete_url_name'] = None
        return ctx


# Balance views
class BalanceListView(OwnerListView):
    model = Balance
    template_name = "manage/list.html"


class BalanceCreateView(OwnerCreateView):
    model = Balance
    fields = ["source", "start_date", "end_date", "currency", "amount"]
    template_name = "manage/form.html"
    success_url = reverse_lazy("expenses:manage_balances")


class BalanceUpdateView(OwnerUpdateView):
    model = Balance
    fields = ["source", "start_date", "end_date", "currency", "amount"]
    template_name = "manage/form.html"
    success_url = reverse_lazy("expenses:manage_balances")


class BalanceDeleteView(OwnerDeleteView):
    model = Balance
    template_name = "manage/confirm_delete.html"
    success_url = reverse_lazy("expenses:manage_balances")


# Transaction views
class TransactionListView(OwnerListView):
    model = Transaction
    template_name = "manage/transactions_list.html"
    paginate_by = 50

    def get_queryset(self):
        qs = super().get_queryset().select_related(
            'category', 'source', 'project', 'payee'
        ).order_by('-date', '-id')

        # Apply filters from query parameters
        category = self.request.GET.get('category')
        if category:
            qs = qs.filter(category__name=category)

        source = self.request.GET.get('source')
        if source:
            qs = qs.filter(source__name=source)

        project = self.request.GET.get('project')
        if project:
            qs = qs.filter(project__name=project)

        currency = self.request.GET.get('currency')
        if currency:
            qs = qs.filter(currency=currency)

        # Date range filtering
        date_from = self.request.GET.get('date_from')
        if date_from:
            try:
                qs = qs.filter(date__gte=date_from)
            except (ValueError, TypeError):
                pass

        date_to = self.request.GET.get('date_to')
        if date_to:
            try:
                qs = qs.filter(date__lte=date_to)
            except (ValueError, TypeError):
                pass

        # Search in description
        search = self.request.GET.get('search')
        if search:
            qs = qs.filter(description__icontains=search)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # Get all categories, sources, projects for filters
        user = self.request.user
        ctx['categories'] = Category.objects.filter(user=user).order_by('name')
        ctx['sources'] = Source.objects.filter(user=user).order_by('name')
        ctx['projects'] = Project.objects.filter(user=user).order_by('name')

        # Get distinct currencies
        ctx['currencies'] = (
            Transaction.objects.filter(user=user)
            .values_list('currency', flat=True)
            .distinct()
            .order_by('currency')
        )

        # Pass current filter values
        ctx['current_filters'] = {
            'category': self.request.GET.get('category', ''),
            'source': self.request.GET.get('source', ''),
            'project': self.request.GET.get('project', ''),
            'currency': self.request.GET.get('currency', ''),
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
            'search': self.request.GET.get('search', ''),
        }

        return ctx

    def post(self, request, *args, **kwargs):
        """Handle transaction updates and deletions via AJAX"""
        action = request.POST.get('action')
        tx_id = request.POST.get('tx_id')

        if not tx_id:
            return JsonResponse({'success': False, 'errors': ['Missing transaction ID']}, status=400)

        try:
            tx = Transaction.objects.get(id=tx_id, user=request.user)
        except Transaction.DoesNotExist:
            return JsonResponse({'success': False, 'errors': ['Transaction not found']}, status=404)

        if action == 'delete_tx':
            tx.delete()
            return JsonResponse({'success': True, 'message': 'Transaction deleted'})

        elif action == 'update_tx':
            # Update category
            category_id = request.POST.get('category_id')
            if category_id:
                try:
                    tx.category = Category.objects.get(id=category_id, user=request.user)
                except Category.DoesNotExist:
                    return JsonResponse({'success': False, 'errors': ['Invalid category']}, status=400)
            else:
                tx.category = None

            # Update source
            source_id = request.POST.get('source_id')
            if source_id:
                try:
                    tx.source = Source.objects.get(id=source_id, user=request.user)
                except Source.DoesNotExist:
                    return JsonResponse({'success': False, 'errors': ['Invalid source']}, status=400)
            else:
                tx.source = None

            # Update project
            project_id = request.POST.get('project_id')
            if project_id:
                try:
                    tx.project = Project.objects.get(id=project_id, user=request.user)
                except Project.DoesNotExist:
                    return JsonResponse({'success': False, 'errors': ['Invalid project']}, status=400)
            else:
                tx.project = None

            # Update comments
            tx.comments = request.POST.get('comments', '')

            tx.save()
            return JsonResponse({'success': True, 'message': 'Transaction updated'})

        return JsonResponse({'success': False, 'errors': ['Invalid action']}, status=400)


class TransactionCreateView(OwnerCreateView):
    model = Transaction
    fields = ["date", "description", "amount", "currency", "source", "category", "project", "payee", "comments"]
    template_name = "manage/form.html"
    success_url = reverse_lazy("expenses:manage_transactions")


class TransactionUpdateView(OwnerUpdateView):
    model = Transaction
    fields = ["date", "description", "amount", "currency", "source", "category", "project", "payee", "comments"]
    template_name = "manage/form.html"
    success_url = reverse_lazy("expenses:manage_transactions")


class TransactionDeleteView(OwnerDeleteView):
    model = Transaction
    template_name = "manage/confirm_delete.html"
    success_url = reverse_lazy("expenses:manage_transactions")

    def get_success_url(self):
        nxt = self.request.GET.get("next") or self.request.POST.get("next")
        if nxt:
            return nxt
        return super().get_success_url()



def register(request):
    """Minimal user registration view using Django's `UserCreationForm`.

    - Uses built-in form for username/password validation.
    - Redirects to the login page after successful registration.
    """
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Cuenta creada. Por favor, ingresá.')
            return redirect('login')
    else:
        form = UserCreationForm()
    return render(request, 'registration/register.html', {'form': form})


def landing(request):
    """Simple landing page at root ('/')."""
    return render(request, 'landing.html')


@login_required
def profile(request):
    """Simple profile page showing username."""
    # Provide user's existing options server-side so the profile quick-add doesn't depend on JS timing
    user = request.user

    # Get user preferences (create if doesn't exist)
    try:
        user_prefs = user.preferences
    except UserPreferences.DoesNotExist:
        user_prefs = UserPreferences.objects.create(
            user=user,
            convert_expenses_to_usd=False  # default
        )

    categories = Category.objects.filter(user=user).order_by('name').values_list('name', flat=True)
    projects = Project.objects.filter(user=user).order_by('name').values_list('name', flat=True)
    payees = Payee.objects.filter(user=user).order_by('name').values_list('name', flat=True)
    sources = Source.objects.filter(user=user).order_by('name').values_list('name', flat=True)
    # Latest transactions (newest first) with related objects fetched to avoid N+1
    tx_qs = (
        Transaction.objects.filter(user=user)
        .only('id', 'description', 'amount', 'currency', 'date', 'category_id', 'project_id', 'payee_id', 'source_id')
        .select_related('category', 'project', 'payee', 'source')
        .order_by('-date', '-id')
    )
    page_number = request.GET.get('page') or 1
    paginator = Paginator(tx_qs, 5)
    tx_page = paginator.get_page(page_number)

    # Category expenses now loaded independently via AJAX (api_category_expenses endpoint)
    context = {
        'user': user,
        'user_preferences': user_prefs,
        'qa_categories': list(categories),
        'qa_projects': list(projects),
        'qa_payees': list(payees),
        'qa_sources': list(sources),
        'tx_page': tx_page,
        'tx_paginator': paginator,
    }
    return render(request, 'profile.html', context)


# Bulk transaction import views
@login_required
def bulk_add_view(request):
    """Display bulk transaction import interface."""
    user = request.user
    
    from .copy_paste.utils import get_available_banks
    
    try:
        banks = get_available_banks()
    except Exception as e:
        messages.error(request, f"Error loading banks: {str(e)}")
        banks = {}
    
    # Get user's sources, categories, and payees
    user_sources = Source.objects.filter(user=user).values_list("name", flat=True)
    user_categories = Category.objects.filter(user=user).values_list("name", flat=True)
    user_payees = Payee.objects.filter(user=user).values_list("name", flat=True)
    
    context = {
        'banks': banks,
        'user_sources': list(user_sources),
        'user_categories': list(user_categories),
        'user_payees': list(user_payees),
    }
    
    return render(request, 'expenses/bulk_add.html', context)


@login_required
@require_POST
def bulk_parse_view(request):
    """Parse pasted transaction data and return preview."""
    user = request.user
    
    try:
        raw_text = request.POST.get("raw_text", "").strip()
        bank = request.POST.get("bank", "").strip()
        currency = request.POST.get("currency", "").strip() or None
        
        if not raw_text:
            return JsonResponse({
                "success": False,
                "errors": ["No data provided"]
            }, status=400)
        
        if not bank:
            return JsonResponse({
                "success": False,
                "errors": ["Bank not selected"]
            }, status=400)
        
        from .copy_paste.parsers import TransactionParser
        from .copy_paste.validators import TransactionValidator
        from .copy_paste.utils import load_yaml_config, format_transaction_for_display
        
        # Load config and parse
        config = load_yaml_config()
        parser = TransactionParser(config)
        transactions, parse_errors = parser.parse(raw_text, bank, currency)
        
        if parse_errors:
            return JsonResponse({
                "success": False,
                "errors": parse_errors
            }, status=400)
        
        # Validate each transaction
        validated = []
        validation_errors = []
        
        for i, txn in enumerate(transactions):
            is_valid, errors = TransactionValidator.validate_transaction(txn)
            
            if not is_valid:
                validation_errors.append({
                    "line": i + 1,
                    "errors": errors
                })
                continue
            
            # Check for duplicates in batch
            if TransactionValidator.check_duplicate_in_batch(txn, validated):
                validation_errors.append({
                    "line": i + 1,
                    "errors": ["Duplicate in batch"]
                })
                continue
            
            # Check for duplicates in DB and mark the transaction
            is_duplicate = TransactionValidator.check_duplicate_in_db(txn, user.id, from_django=True)
            if is_duplicate:
                txn['is_duplicate'] = True
            
            validated.append(txn)
        
        # Format for display
        display_transactions = [format_transaction_for_display(t) for t in validated]
        
        return JsonResponse({
            "success": True,
            "transactions": display_transactions,
            "validation_errors": validation_errors,
            "total_parsed": len(transactions),
            "total_valid": len(validated),
        })
    
    except Exception as e:
        return JsonResponse({
            "success": False,
            "errors": [f"Error: {str(e)}"]
        }, status=500)


@login_required
@require_POST
def bulk_confirm_view(request):
    """Confirm and save selected transactions."""
    user = request.user
    
    try:
        import json
        data = json.loads(request.body)
        transactions = data.get("transactions", [])
        
        if not transactions:
            return JsonResponse({
                "success": False,
                "errors": ["No transactions to save"]
            }, status=400)
        
        from .copy_paste.validators import TransactionValidator
        from decimal import Decimal
        
        created_count = 0
        errors = []
        
        # Helper function to get or create related models
        def get_or_create_model(model, name):
            if not name:
                return None
            obj = model.objects.filter(user=user, name__iexact=name.strip()).first()
            if obj:
                return obj
            return model.objects.create(user=user, name=name.strip())
        
        for i, txn_data in enumerate(transactions):
            try:
                # Validate
                txn = {
                    "date": txn_data.get("date"),
                    "description": txn_data.get("description"),
                    "amount": Decimal(str(txn_data.get("amount", 0))),
                    "currency": txn_data.get("currency"),
                    "source": txn_data.get("source"),
                }
                
                is_valid, val_errors = TransactionValidator.validate_transaction(txn)
                if not is_valid:
                    errors.append({
                        "index": i,
                        "errors": val_errors
                    })
                    continue
                
                # Get or create source
                source = None
                if txn["source"]:
                    # Keep full source name including bank prefix (e.g., "visa:3048")
                    source_name = txn["source"]
                    source, _ = Source.objects.get_or_create(
                        user=user,
                        name=source_name
                    )
                
                # Get or create category and payee
                category_name = txn_data.get("category")
                payee_name = txn_data.get("payee")
                
                category = get_or_create_model(Category, category_name) if category_name else None
                payee = get_or_create_model(Payee, payee_name) if payee_name else None
                
                # Create transaction
                transaction = Transaction.objects.create(
                    user=user,
                    date=txn["date"],
                    description=txn["description"],
                    amount=txn["amount"],
                    currency=txn["currency"],
                    source=source,
                    category=category,
                    payee=payee,
                )
                
                created_count += 1
            
            except Exception as e:
                errors.append({
                    "index": i,
                    "errors": [str(e)]
                })
        
        if created_count == 0:
            return JsonResponse({
                "success": False,
                "errors": errors,
                "message": "No transactions were saved"
            }, status=400)
        
        response_data = {
            "success": True,
            "created": created_count,
            "message": f"{created_count} transaction(s) created successfully"
        }
        
        if errors:
            response_data["errors"] = errors
        
        return JsonResponse(response_data)
    
    except json.JSONDecodeError:
        return JsonResponse({
            "success": False,
            "errors": ["Invalid JSON"]
        }, status=400)
    
    except Exception as e:
        return JsonResponse({
            "success": False,
            "errors": [f"Error: {str(e)}"]
        }, status=500)


REQUEST_TOKEN_URL = 'https://secure.splitwise.com/oauth/request_token'
AUTHORIZE_URL = 'https://secure.splitwise.com/oauth/authorize'
ACCESS_TOKEN_URL = 'https://secure.splitwise.com/oauth/access_token'
API_BASE = 'https://secure.splitwise.com/api/v3.0'

@login_required
def splitwise_connect(request):
    callback = request.build_absolute_uri(reverse('expenses:splitwise_callback'))
    oauth = OAuth1Session(settings.SPLITWISE_CONSUMER_KEY, client_secret=settings.SPLITWISE_CONSUMER_SECRET, callback_uri=callback)
    fetch_response = oauth.fetch_request_token(REQUEST_TOKEN_URL)
    request.session['splitwise_oauth_token'] = fetch_response.get('oauth_token')
    request.session['splitwise_oauth_token_secret'] = fetch_response.get('oauth_token_secret')
    auth_url = oauth.authorization_url(AUTHORIZE_URL)
    return redirect(auth_url)

@login_required
def splitwise_callback(request):
    token = request.session.get('splitwise_oauth_token')
    token_secret = request.session.get('splitwise_oauth_token_secret')
    oauth_verifier = request.GET.get('oauth_verifier')
    oauth = OAuth1Session(settings.SPLITWISE_CONSUMER_KEY,
                          client_secret=settings.SPLITWISE_CONSUMER_SECRET,
                          resource_owner_key=token,
                          resource_owner_secret=token_secret,
                          verifier=oauth_verifier)
    oauth_tokens = oauth.fetch_access_token(ACCESS_TOKEN_URL)
    access_token = oauth_tokens.get('oauth_token')
    access_secret = oauth_tokens.get('oauth_token_secret')

    split_user_id = None
    raw = None
    try:
        resp = oauth.get(f"{API_BASE}/get_current_user")
        if resp.ok:
            raw = resp.json()
            split_user = raw.get('user') or {}
            split_user_id = str(split_user.get('id') or split_user.get('user_id') or '')
    except Exception:
        logger.exception("Error obteniendo usuario de Splitwise")

    # Check if this Splitwise account is already connected to another user
    if split_user_id:
        existing = SplitwiseAccount.objects.filter(splitwise_user_id=split_user_id).exclude(user=request.user).first()
        if existing:
            messages.error(
                request,
                f"Esta cuenta de Splitwise ya está conectada a otro usuario. "
                f"Si crees que esto es un error, contacta al soporte."
            )
            return redirect('expenses:splitwise_status')

    account, _ = SplitwiseAccount.objects.get_or_create(user=request.user)
    account.oauth_token = access_token
    account.oauth_token_secret = access_secret
    if split_user_id:
        account.splitwise_user_id = split_user_id
    if raw:
        account.raw = raw
    account.save()
    
    messages.success(request, "✅ Cuenta de Splitwise conectada exitosamente")
    return redirect(request.GET.get('next') or '/')


@login_required
def splitwise_status(request):
    """Display Splitwise connection status and offer connect action."""
    account = SplitwiseAccount.objects.filter(user=request.user).first()
    connected = bool(account and account.oauth_token and account.oauth_token_secret)
    context = {
        "account": account,
        "connected": connected,
    }
    return render(request, "manage/splitwise.html", context)


@login_required
@require_GET
def api_recent_transactions(request):
    """API endpoint: Return recent transactions as JSON for async loading."""
    user = request.user
    page_num = int(request.GET.get('page', 1))
    
    recent_tx = Transaction.objects.filter(user=user).order_by('-date', '-id')
    paginator = Paginator(recent_tx, 5)
    
    try:
        tx_page = paginator.page(page_num)
    except:
        tx_page = paginator.page(1)
    
    transactions = [
        {
            'id': t.pk,
            'description': t.description,
            'amount': str(t.amount),
            'currency': t.currency,
            'date': t.date.isoformat(),
            'edit_url': reverse('expenses:manage_transaction_edit', args=[t.pk]),
        }
        for t in tx_page
    ]
    
    return JsonResponse({
        'transactions': transactions,
        'has_previous': tx_page.has_previous(),
        'has_next': tx_page.has_next(),
        'previous_page': tx_page.previous_page_number() if tx_page.has_previous() else None,
        'next_page': tx_page.next_page_number() if tx_page.has_next() else None,
        'current_page': tx_page.number,
        'num_pages': paginator.num_pages,
        'page_range': list(paginator.page_range),
    })


def get_category_expenses(user, month_qs, convert_to_usd=False):
    """
    Calculate category expenses for a given month's transactions.

    Args:
        user: User instance
        month_qs: QuerySet of Transaction objects for the month
        convert_to_usd: If True, convert all amounts to USD using to_usd()
                       If False, use original amounts with currency

    Returns:
        tuple: (cat_expenses, missing_rates)
            cat_expenses: list of dicts with 'category', 'currency', 'total'
            missing_rates: count of transactions without exchange rates (only when convert_to_usd=True)
    """
    if convert_to_usd:
        # Convert to USD and group by category
        category_totals = {}
        missing_rates_count = 0

        # Select related to avoid N+1 queries
        transactions = month_qs.select_related('category')

        for tx in transactions:
            cat_name = tx.category.name if tx.category else 'Sin categoría'

            # Use to_usd() method which handles caching
            amount_usd = tx.to_usd()

            if amount_usd is None:
                missing_rates_count += 1
                continue

            # Add to category total (use absolute value)
            if cat_name not in category_totals:
                category_totals[cat_name] = Decimal('0')
            category_totals[cat_name] += abs(amount_usd)

        # Convert to list format sorted by total descending
        cat_expenses = [
            {
                'category': cat_name,
                'currency': 'USD',
                'total': str(total.quantize(Decimal('0.01'))),
            }
            for cat_name, total in sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
        ]

        return cat_expenses, missing_rates_count

    else:
        # Group by category AND currency (using absolute values)
        category_currency_totals = {}
        transactions = month_qs.select_related('category')

        for tx in transactions:
            cat_name = tx.category.name if tx.category else 'Sin categoría'
            currency = tx.currency
            key = (cat_name, currency)

            if key not in category_currency_totals:
                category_currency_totals[key] = Decimal('0')
            # Use absolute value to include both income and expenses
            category_currency_totals[key] += abs(tx.amount)

        # Sort by category name, then currency
        cat_expenses = [
            {
                'category': cat_name,
                'currency': currency,
                'total': str(total.quantize(Decimal('0.01'))),
            }
            for (cat_name, currency), total in sorted(category_currency_totals.items())
        ]

        return cat_expenses, 0


@login_required
@require_GET
def api_category_expenses(request):
    """API endpoint: Return category expenses by currency for a month as JSON."""
    user = request.user

    # Helper functions for month handling
    def month_str(y, m):
        return f"{y:04d}-{m:02d}"

    def prev_month(y, m):
        return (y - 1, 12) if m == 1 else (y, m - 1)

    def next_month(y, m):
        return (y + 1, 1) if m == 12 else (y, m + 1)

    # Parse month parameter
    today = datetime.date.today()
    current_year, current_month = today.year, today.month
    m_param = request.GET.get('m', '')
    sel_year, sel_month = current_year, current_month

    if m_param:
        try:
            parts = m_param.split('-')
            y = int(parts[0])
            m = int(parts[1])
            if 1 <= m <= 12:
                sel_year, sel_month = y, m
        except Exception:
            pass

    # Get user preference from database (default to False)
    try:
        prefs = user.preferences
        convert_to_usd = prefs.convert_expenses_to_usd
    except UserPreferences.DoesNotExist:
        convert_to_usd = False

    # Get transactions for selected month
    first_day = datetime.date(sel_year, sel_month, 1)
    ny, nm = next_month(sel_year, sel_month)
    next_first = datetime.date(ny, nm, 1)

    # Include all non-zero transactions (use absolute values in aggregation)
    month_qs = Transaction.objects.filter(
        user=user,
        date__gte=first_day,
        date__lt=next_first,
    ).exclude(amount=0)

    # Use helper function to calculate expenses
    cat_expenses, missing_rates = get_category_expenses(user, month_qs, convert_to_usd)

    py, pm = prev_month(sel_year, sel_month)

    return JsonResponse({
        'cat_expenses': cat_expenses,
        'selected_month_str': month_str(sel_year, sel_month),
        'm_current': month_str(current_year, current_month),
        'm_prev': month_str(py, pm),
        'convert_to_usd': convert_to_usd,
        'missing_rates': missing_rates,
    })


@login_required
@require_GET
def api_project_expenses(request):
    """API endpoint: Return total expenses by project (all time, no month filter)."""
    user = request.user

    # Get user preference from database (default to False)
    try:
        prefs = user.preferences
        convert_to_usd = prefs.convert_expenses_to_usd
    except UserPreferences.DoesNotExist:
        convert_to_usd = False

    # Get all transactions with a project (filter out null projects, include both income/expenses)
    all_txs = Transaction.objects.filter(user=user, project__isnull=False).exclude(amount=0)

    if convert_to_usd:
        # Convert to USD and group by project (using absolute values)
        project_totals = {}
        missing_rates_count = 0
        transactions = all_txs.select_related('project')

        for tx in transactions:
            proj_name = tx.project.name
            amount_usd = tx.to_usd()

            if amount_usd is None:
                missing_rates_count += 1
                continue

            if proj_name not in project_totals:
                project_totals[proj_name] = Decimal('0')
            project_totals[proj_name] += abs(amount_usd)

        proj_expenses = [
            {
                'project': proj_name,
                'currency': 'USD',
                'total': str(total.quantize(Decimal('0.01'))),
            }
            for proj_name, total in sorted(project_totals.items(), key=lambda x: x[1], reverse=True)
        ]
        missing_rates = missing_rates_count
    else:
        # Group by project AND currency (using absolute values)
        project_currency_totals = {}
        transactions = all_txs.select_related('project')

        for tx in transactions:
            proj_name = tx.project.name
            currency = tx.currency
            key = (proj_name, currency)

            if key not in project_currency_totals:
                project_currency_totals[key] = Decimal('0')
            # Use absolute value to include both income and expenses
            project_currency_totals[key] += abs(tx.amount)

        # Sort by project name, then currency
        proj_expenses = [
            {
                'project': proj_name,
                'currency': currency,
                'total': str(total.quantize(Decimal('0.01'))),
            }
            for (proj_name, currency), total in sorted(project_currency_totals.items())
        ]
        missing_rates = 0

    return JsonResponse({
        'proj_expenses': proj_expenses,
        'convert_to_usd': convert_to_usd,
        'missing_rates': missing_rates,
    })


@login_required
@require_GET
def api_source_expenses(request):
    """API endpoint: Return monthly expenses by source (with month navigation like categories)."""
    user = request.user

    # Helper functions for month handling
    def month_str(y, m):
        return f"{y:04d}-{m:02d}"

    def prev_month(y, m):
        return (y - 1, 12) if m == 1 else (y, m - 1)

    def next_month(y, m):
        return (y + 1, 1) if m == 12 else (y, m + 1)

    # Parse month parameter
    today = datetime.date.today()
    current_year, current_month = today.year, today.month
    m_param = request.GET.get('m', '')
    sel_year, sel_month = current_year, current_month

    if m_param:
        try:
            parts = m_param.split('-')
            y = int(parts[0])
            m = int(parts[1])
            if 1 <= m <= 12:
                sel_year, sel_month = y, m
        except Exception:
            pass

    # Get user preference from database (default to False)
    try:
        prefs = user.preferences
        convert_to_usd = prefs.convert_expenses_to_usd
    except UserPreferences.DoesNotExist:
        convert_to_usd = False

    # Get transactions for selected month with source (filter out null sources)
    first_day = datetime.date(sel_year, sel_month, 1)
    ny, nm = next_month(sel_year, sel_month)
    next_first = datetime.date(ny, nm, 1)

    # Include all non-zero transactions (both positive and negative)
    # We'll use absolute values when aggregating
    month_qs = Transaction.objects.filter(
        user=user,
        date__gte=first_day,
        date__lt=next_first,
        source__isnull=False,
    ).exclude(amount=0)

    if convert_to_usd:
        # Convert to USD and group by source (using absolute values)
        source_totals = {}
        missing_rates_count = 0
        transactions = month_qs.select_related('source')

        for tx in transactions:
            src_name = tx.source.name
            amount_usd = tx.to_usd()

            if amount_usd is None:
                missing_rates_count += 1
                continue

            if src_name not in source_totals:
                source_totals[src_name] = Decimal('0')
            # Use absolute value to include both income and expenses
            source_totals[src_name] += abs(amount_usd)

        src_expenses = [
            {
                'source': src_name,
                'currency': 'USD',
                'total': str(total.quantize(Decimal('0.01'))),
            }
            for src_name, total in sorted(source_totals.items(), key=lambda x: x[1], reverse=True)
        ]
        missing_rates = missing_rates_count
    else:
        # Group by source AND currency (using absolute values)
        source_currency_totals = {}
        transactions = month_qs.select_related('source')

        for tx in transactions:
            src_name = tx.source.name
            currency = tx.currency
            key = (src_name, currency)

            if key not in source_currency_totals:
                source_currency_totals[key] = Decimal('0')
            # Use absolute value to include both income and expenses
            source_currency_totals[key] += abs(tx.amount)

        # Sort by source name, then currency
        src_expenses = [
            {
                'source': src_name,
                'currency': currency,
                'total': str(total.quantize(Decimal('0.01'))),
            }
            for (src_name, currency), total in sorted(source_currency_totals.items())
        ]
        missing_rates = 0

    py, pm = prev_month(sel_year, sel_month)

    return JsonResponse({
        'src_expenses': src_expenses,
        'selected_month_str': month_str(sel_year, sel_month),
        'm_current': month_str(current_year, current_month),
        'm_prev': month_str(py, pm),
        'convert_to_usd': convert_to_usd,
        'missing_rates': missing_rates,
    })


@login_required
@require_http_methods(["POST"])
def update_forwarding_email(request):
    """Update user's forwarding email address"""
    try:
        cfg = UserEmailConfig.objects.get(user=request.user, active=True)
    except UserEmailConfig.DoesNotExist:
        messages.error(request, "No tienes una configuración de email.")
        return redirect('expenses:manage_emails')

    forwarding_email = request.POST.get('forwarding_email', '').strip()

    # Allow clearing the field
    if not forwarding_email:
        cfg.forwarding_email = None
        cfg.save()
        messages.success(request, "Email de reenvío eliminado correctamente.")
        return redirect('expenses:manage_emails')

    # Validate email format (basic)
    try:
        validate_email(forwarding_email)
    except ValidationError:
        messages.error(request, "Email inválido. Por favor verifica el formato.")
        return redirect('expenses:manage_emails')

    # Check for uniqueness (catch IntegrityError)
    try:
        cfg.forwarding_email = forwarding_email
        cfg.save()
        messages.success(request, f"Email de reenvío actualizado a: {forwarding_email}")
    except IntegrityError:
        messages.error(request, "Este email ya está en uso por otro usuario.")

    return redirect('expenses:manage_emails')


@login_required
@require_http_methods(["POST"])
def update_user_preference(request):
    """Update user preference via AJAX"""
    preference_key = request.POST.get('key')
    preference_value = request.POST.get('value')

    if preference_key == 'convert_expenses_to_usd':
        try:
            with transaction.atomic():
                # Get or create user preferences
                prefs, created = UserPreferences.objects.get_or_create(user=request.user)
                prefs.convert_expenses_to_usd = (preference_value == 'true')
                prefs.save()

            return JsonResponse({
                'success': True,
                'message': 'Preference updated'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)

    return JsonResponse({
        'success': False,
        'error': 'Invalid preference key'
    }, status=400)