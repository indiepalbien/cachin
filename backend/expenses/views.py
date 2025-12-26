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
from .models import Category, Project, Payee, Source, Exchange, Balance, Transaction, UserEmailMessage, UserEmailConfig, PendingTransaction, SplitwiseAccount, DefaultExchangeRate, UserProfile, UserPreferences
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


def _get_onboarding_context(user):
    """Helper to get onboarding context for templates."""
    try:
        profile = user.profile
        return {
            'is_onboarding': profile.onboarding_step > 0,
            'onboarding_step': profile.onboarding_step,
            'onboarding_total_steps': 5,
        }
    except UserProfile.DoesNotExist:
        return {
            'is_onboarding': False,
            'onboarding_step': 0,
            'onboarding_total_steps': 5,
        }


def _advance_onboarding(user):
    """Helper to advance user to next onboarding step."""
    try:
        profile = user.profile
        if profile.onboarding_step > 0 and profile.onboarding_step < 5:
            profile.onboarding_step += 1
            profile.save()
            return profile.onboarding_step
        elif profile.onboarding_step == 5:
            profile.onboarding_step = 0
            profile.save()
            return 0
    except UserProfile.DoesNotExist:
        pass
    return None


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
    - Returns HTML fragment for HTMX requests or redirects with messages for normal POST.
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
        errors.append("Importe requerido.")
    if not date_str:
        errors.append("Fecha requerida.")
    if not currency:
        errors.append("Moneda requerida.")

    # Validate currency format (ISO-4217 style: 3 letters)
    if currency and (len(currency) != 3 or not currency.isalpha()):
        errors.append("La moneda debe ser un código de 3 letras (ISO-4217).")

    # If any errors, respond appropriately
    if errors:
        error_msg = " / ".join(errors)
        if request.htmx:
            return HttpResponse(
                f'<span style="color:#dc2626;opacity:1">{error_msg}</span>',
                status=400
            )
        for e in errors:
            messages.error(request, e)
        return redirect("profile")

    # Parse amount and date
    try:
        amount_dec = Decimal(amount)
    except (InvalidOperation, TypeError):
        msg = "El importe debe ser un número."
        if request.htmx:
            return HttpResponse(f'<span style="color:#dc2626;opacity:1">{msg}</span>', status=400)
        messages.error(request, msg)
        return redirect("profile")

    try:
        tx_date = datetime.date.fromisoformat(date_str)
    except Exception:
        msg = "Formato de fecha inválido. Usar YYYY-MM-DD."
        if request.htmx:
            return HttpResponse(f'<span style="color:#dc2626;opacity:1">{msg}</span>', status=400)
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
        if request.htmx:
            return HttpResponse(f'<span style="color:var(--accent);opacity:1">{success_msg}</span>')
        messages.success(request, success_msg)
    except Exception as e:
        err = f"Error creando transacción: {e}"
        if request.htmx:
            return HttpResponse(f'<span style="color:#dc2626;opacity:1">{err}</span>', status=500)
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
        ("Categorias", "expenses:manage_categories"),
        ("Proyectos", "expenses:manage_projects"),
        ("Beneficiarios", "expenses:manage_payees"),
        ("Orígenes", "expenses:manage_sources"),
        ("Cotizaciones", "expenses:manage_exchanges"),
        ("Balances", "expenses:manage_balances"),
        ("Transacciones", "expenses:manage_transactions"),
        ("Splitwise", "expenses:splitwise_status"),
        ("Emails", "expenses:manage_emails"),
        ("Pendientes", "expenses:manage_pending_transactions"),
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
    """DEPRECATED: Redirect to manage_transactions with uncategorized filter."""
    return redirect(reverse("expenses:manage_transactions") + "?category=__null__")


def redirect_to_uncategorized(request):
    """Redirect to the unified transactions view with uncategorized filter."""
    return redirect(reverse("expenses:manage_transactions") + "?category=__null__")


def edit_category_transactions(request):
    """DEPRECATED: Redirect to manage_transactions with appropriate filters."""
    # Extract query parameters and redirect to unified view
    params = []
    
    category_name = request.GET.get('category', '')
    if category_name:
        params.append(f"category={category_name}")
    
    source_name = request.GET.get('source', '')
    if source_name:
        params.append(f"source={source_name}")
    
    project_name = request.GET.get('project', '')
    if project_name:
        params.append(f"project={project_name}")
    
    currency = request.GET.get('currency', '')
    if currency:
        params.append(f"currency={currency}")
    
    month_param = request.GET.get('month', '')
    if month_param:
        params.append(f"month={month_param}")
    
    query_string = "&".join(params) if params else ""
    url = reverse("expenses:manage_transactions")
    if query_string:
        url += f"?{query_string}"
    
    return redirect(url)


def redirect_to_filtered_transactions(request):
    """Redirect to the unified transactions view with filters from query parameters."""
    # Extract query parameters and redirect to unified view
    params = []
    
    category_name = request.GET.get('category', '')
    if category_name:
        params.append(f"category={category_name}")
    
    source_name = request.GET.get('source', '')
    if source_name:
        params.append(f"source={source_name}")
    
    project_name = request.GET.get('project', '')
    if project_name:
        params.append(f"project={project_name}")
    
    currency = request.GET.get('currency', '')
    if currency:
        params.append(f"currency={currency}")
    
    month_param = request.GET.get('month', '')
    if month_param:
        params.append(f"month={month_param}")
    
    query_string = "&".join(params) if params else ""
    url = reverse("expenses:manage_transactions")
    if query_string:
        url += f"?{query_string}"
    
    return redirect(url)


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
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(_get_onboarding_context(self.request.user))
        return ctx
    
    def post(self, request, *args, **kwargs):
        """Handle onboarding confirmation."""
        if request.POST.get('onboarding_confirm'):
            _advance_onboarding(request.user)
            messages.success(request, '¡Categorías configuradas! Ahora veamos los proyectos.')
            return redirect('expenses:manage_projects')
        return super().post(request, *args, **kwargs)


class CategoryCreateView(OwnerCreateView):
    model = Category
    fields = ["name", "counts_to_total", "description"]
    template_name = "manage/form.html"
    success_url = reverse_lazy("expenses:manage_categories")


class CategoryUpdateView(OwnerUpdateView):
    model = Category
    fields = ["name", "counts_to_total", "description"]
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
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(_get_onboarding_context(self.request.user))
        return ctx
    
    def post(self, request, *args, **kwargs):
        """Handle onboarding confirmation."""
        if request.POST.get('onboarding_confirm'):
            _advance_onboarding(request.user)
            messages.success(request, '¡Proyectos configurados! Ahora configuremos Splitwise.')
            return redirect('expenses:splitwise_status')
        return super().post(request, *args, **kwargs)


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
        # Add onboarding context
        ctx.update(_get_onboarding_context(self.request.user))
        # Pass email config to template for forwarding email form
        ctx['email_config'] = cfg
        return ctx
    
    def post(self, request, *args, **kwargs):
        """Handle onboarding confirmation and email update."""
        # Handle user email update
        if request.POST.get('user_email'):
            user_email = request.POST.get('user_email', '').strip()
            cfg = UserEmailConfig.objects.filter(user=request.user).first()
            if cfg:
                cfg.user_email = user_email
                cfg.save()
                messages.success(request, f'✅ Email personal guardado: {user_email}')
        
        # Handle onboarding confirmation
        if request.POST.get('onboarding_confirm'):
            _advance_onboarding(request.user)
            messages.success(request, '¡Ya casi terminamos! Un último paso.')
            return redirect('profile')
        
        return redirect('expenses:manage_emails')


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
        # Special value "__null__" means filter by null/empty
        category = self.request.GET.get('category')
        if category:
            if category == '__null__':
                qs = qs.filter(category__isnull=True)
            else:
                qs = qs.filter(category__name=category)

        source = self.request.GET.get('source')
        if source:
            if source == '__null__':
                qs = qs.filter(source__isnull=True)
            else:
                qs = qs.filter(source__name=source)

        project = self.request.GET.get('project')
        if project:
            if project == '__null__':
                qs = qs.filter(project__isnull=True)
            else:
                qs = qs.filter(project__name=project)

        payee = self.request.GET.get('payee')
        if payee:
            if payee == '__null__':
                qs = qs.filter(payee__isnull=True)
            else:
                qs = qs.filter(payee__name=payee)

        currency = self.request.GET.get('currency')
        if currency:
            qs = qs.filter(currency=currency)

        # Month filtering (format: YYYY-MM)
        month_param = self.request.GET.get('month')
        if month_param:
            try:
                year, month = map(int, month_param.split('-'))
                import calendar
                last_day = calendar.monthrange(year, month)[1]
                start_date = datetime.date(year, month, 1)
                end_date = datetime.date(year, month, last_day)
                qs = qs.filter(date__gte=start_date, date__lte=end_date)
            except (ValueError, AttributeError):
                pass  # Invalid month format, skip filter

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

        # Get all categories, sources, projects, payees for filters
        user = self.request.user
        ctx['categories'] = Category.objects.filter(user=user).order_by('name')
        ctx['sources'] = Source.objects.filter(user=user).order_by('name')
        ctx['projects'] = Project.objects.filter(user=user).order_by('name')
        ctx['payees'] = Payee.objects.filter(user=user).order_by('name')

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
            'payee': self.request.GET.get('payee', ''),
            'currency': self.request.GET.get('currency', ''),
            'month': self.request.GET.get('month', ''),
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
            'search': self.request.GET.get('search', ''),
        }

        return ctx

    def post(self, request, *args, **kwargs):
        """Handle transaction updates and deletions via HTMX/AJAX"""
        action = request.POST.get('action')
        tx_id = request.POST.get('tx_id')

        if not tx_id:
            if request.htmx:
                return HttpResponse("ID de transacción requerido", status=400)
            return JsonResponse({'success': False, 'errors': ['Missing transaction ID']}, status=400)

        try:
            tx = Transaction.objects.get(id=tx_id, user=request.user)
        except Transaction.DoesNotExist:
            if request.htmx:
                return HttpResponse("Transacción no encontrada", status=404)
            return JsonResponse({'success': False, 'errors': ['Transaction not found']}, status=404)

        if action == 'delete_tx':
            tx.delete()
            if request.htmx:
                return HttpResponse("")  # Empty response removes the element
            return JsonResponse({'success': True, 'message': 'Transaction deleted'})

        elif action == 'update_tx':
            # Update category
            category_id = request.POST.get('category_id')
            if category_id:
                try:
                    tx.category = Category.objects.get(id=category_id, user=request.user)
                except Category.DoesNotExist:
                    if request.htmx:
                        return HttpResponse(
                            '<span class="spinner" style="display:none"></span>'
                            '<span class="status-text" style="color:#dc2626;background:#fee2e2;'
                            'padding:0.25rem 0.5rem;border-radius:3px;display:inline-block">'
                            'Categoría inválida</span>',
                            status=400
                        )
                    return JsonResponse({'success': False, 'errors': ['Invalid category']}, status=400)
            else:
                tx.category = None

            # Update source
            source_id = request.POST.get('source_id')
            if source_id:
                try:
                    tx.source = Source.objects.get(id=source_id, user=request.user)
                except Source.DoesNotExist:
                    if request.htmx:
                        return HttpResponse(
                            '<span class="spinner" style="display:none"></span>'
                            '<span class="status-text" style="color:#dc2626;background:#fee2e2;'
                            'padding:0.25rem 0.5rem;border-radius:3px;display:inline-block">'
                            'Origen inválido</span>',
                            status=400
                        )
                    return JsonResponse({'success': False, 'errors': ['Invalid source']}, status=400)
            else:
                tx.source = None

            # Update project
            project_id = request.POST.get('project_id')
            if project_id:
                try:
                    tx.project = Project.objects.get(id=project_id, user=request.user)
                except Project.DoesNotExist:
                    if request.htmx:
                        return HttpResponse(
                            '<span class="spinner" style="display:none"></span>'
                            '<span class="status-text" style="color:#dc2626;background:#fee2e2;'
                            'padding:0.25rem 0.5rem;border-radius:3px;display:inline-block">'
                            'Proyecto inválido</span>',
                            status=400
                        )
                    return JsonResponse({'success': False, 'errors': ['Invalid project']}, status=400)
            else:
                tx.project = None

            # Update comments
            tx.comments = request.POST.get('comments', '')

            tx.save()
            if request.htmx:
                return HttpResponse(
                    '<span class="spinner" style="display:none"></span>'
                    '<span class="status-text" style="color:#059669;background:#d1fae5;'
                    'padding:0.25rem 0.5rem;border-radius:3px;display:inline-block">'
                    '✓ Guardado</span>'
                )
            return JsonResponse({'success': True, 'message': 'Transaction updated'})

        if request.htmx:
            return HttpResponse("Acción inválida", status=400)
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
    """
    Landing page at root ('/').

    If user is authenticated and has completed onboarding, redirect to dashboard.
    Otherwise, show the landing page.
    """
    if request.user.is_authenticated:
        try:
            profile = request.user.profile
            # If onboarding is complete (step 0), redirect to dashboard
            if profile.onboarding_step == 0:
                return redirect('profile')
        except UserProfile.DoesNotExist:
            # If profile doesn't exist, let middleware handle it
            pass

    return render(request, 'landing.html')


@login_required
def profile(request):
    """Simple profile page showing username."""
    user = request.user
    
    # Handle onboarding completion
    if request.method == 'POST' and request.POST.get('onboarding_complete'):
        try:
            profile_obj = user.profile
            profile_obj.onboarding_step = 0
            profile_obj.save()
            messages.success(request, '¡Bienvenido! Tu cuenta está lista para usar.')
        except UserProfile.DoesNotExist:
            pass
        return redirect('profile')

    # Get user preferences (create if doesn't exist)
    try:
        user_prefs = user.preferences
    except UserPreferences.DoesNotExist:
        user_prefs = UserPreferences.objects.create(
            user=user,
            convert_expenses_to_usd=False  # default
        )
    
    # Provide user's existing options server-side so the profile quick-add doesn't depend on JS timing
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
    context.update(_get_onboarding_context(user))
    
    # Get email config for onboarding step 4
    try:
        context['email_config'] = user.useremailconfig
    except:
        context['email_config'] = None
    
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
                
                # Get or create source (user-provided from form)
                source = None
                source_name = txn_data.get("source")
                if source_name:
                    source, _ = Source.objects.get_or_create(
                        user=user,
                        name=source_name.strip()
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
    user = request.user
    
    if request.method == 'POST' and request.POST.get('onboarding_confirm'):
        _advance_onboarding(user)
        messages.info(request, 'Ahora configuremos el correo electrónico.')
        return redirect('profile')  # Will show email config in profile
    
    account = SplitwiseAccount.objects.filter(user=user).first()
    connected = bool(account and account.oauth_token and account.oauth_token_secret)
    context = {
        "account": account,
        "connected": connected,
    }
    context.update(_get_onboarding_context(user))
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
        tuple: (cat_expenses, missing_rates, subtotals)
            cat_expenses: list of dicts with 'category', 'currency', 'total', 'counts_to_total'
            missing_rates: count of transactions without exchange rates (only when convert_to_usd=True)
            subtotals: dict of currency -> subtotal (only for categories where counts_to_total=True)
    """
    # Get all user categories with counts_to_total flag
    categories_map = {cat.name: cat.counts_to_total for cat in Category.objects.filter(user=user)}

    if convert_to_usd:
        # Convert to USD and group by category
        category_totals = {}
        missing_rates_count = 0
        subtotal_usd = Decimal('0')

        # Select related to avoid N+1 queries
        transactions = month_qs.select_related('category')

        for tx in transactions:
            cat_name = tx.category.name if tx.category else 'Sin categoría'
            counts_to_total = categories_map.get(cat_name, True)  # Default True for 'Sin categoría'

            # Use to_usd() method which handles caching
            amount_usd = tx.to_usd()

            if amount_usd is None:
                missing_rates_count += 1
                continue

            # Add to category total (keep sign: positive = expense, negative = income)
            if cat_name not in category_totals:
                category_totals[cat_name] = Decimal('0')
            category_totals[cat_name] += amount_usd

            # Add to subtotal if category counts
            if counts_to_total:
                subtotal_usd += amount_usd

        # Convert to list format sorted by total descending
        cat_expenses = [
            {
                'category': cat_name,
                'currency': 'USD',
                'total': str(total.quantize(Decimal('0.01'))),
                'counts_to_total': categories_map.get(cat_name, True),
            }
            for cat_name, total in sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
        ]

        subtotals = {'USD': str(subtotal_usd.quantize(Decimal('0.01')))}
        return cat_expenses, missing_rates_count, subtotals

    else:
        # Group by category AND currency (keep sign: positive = expense, negative = income)
        category_currency_totals = {}
        currency_subtotals = {}  # Track subtotal per currency
        transactions = month_qs.select_related('category')

        for tx in transactions:
            cat_name = tx.category.name if tx.category else 'Sin categoría'
            currency = tx.currency
            key = (cat_name, currency)
            counts_to_total = categories_map.get(cat_name, True)

            if key not in category_currency_totals:
                category_currency_totals[key] = Decimal('0')
            category_currency_totals[key] += tx.amount

            # Add to currency subtotal if category counts
            if counts_to_total:
                if currency not in currency_subtotals:
                    currency_subtotals[currency] = Decimal('0')
                currency_subtotals[currency] += tx.amount

        # Sort by category name, then currency
        cat_expenses = [
            {
                'category': cat_name,
                'currency': currency,
                'total': str(total.quantize(Decimal('0.01'))),
                'counts_to_total': categories_map.get(cat_name, True),
            }
            for (cat_name, currency), total in sorted(category_currency_totals.items())
        ]

        subtotals = {curr: str(total.quantize(Decimal('0.01'))) for curr, total in currency_subtotals.items()}
        return cat_expenses, 0, subtotals


@login_required
@require_GET
def api_category_expenses(request):
    """API endpoint: Return category expenses by currency for a month (HTMX HTML or JSON)."""
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
    cat_expenses, missing_rates, subtotals = get_category_expenses(user, month_qs, convert_to_usd)

    py, pm = prev_month(sel_year, sel_month)

    context = {
        'cat_expenses': cat_expenses,
        'selected_month_str': month_str(sel_year, sel_month),
        'm_current': month_str(current_year, current_month),
        'm_prev': month_str(py, pm),
        'convert_to_usd': convert_to_usd,
        'missing_rates': missing_rates,
        'subtotals': subtotals,
    }

    # HTMX request - return HTML
    if request.htmx:
        return render(request, 'expenses/partials/category_expenses.html', context)

    # Legacy JSON response
    return JsonResponse(context)


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
        # Convert to USD and group by project (keep sign: positive = expense, negative = income)
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
            project_totals[proj_name] += amount_usd

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
        # Group by project AND currency (keep sign: positive = expense, negative = income)
        project_currency_totals = {}
        transactions = all_txs.select_related('project')

        for tx in transactions:
            proj_name = tx.project.name
            currency = tx.currency
            key = (proj_name, currency)

            if key not in project_currency_totals:
                project_currency_totals[key] = Decimal('0')
            # Keep sign to distinguish income from expenses
            project_currency_totals[key] += tx.amount

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

    context = {
        'proj_expenses': proj_expenses,
        'convert_to_usd': convert_to_usd,
        'missing_rates': missing_rates,
    }

    # HTMX request - return HTML
    if request.htmx:
        return render(request, 'expenses/partials/project_expenses.html', context)

    # Legacy JSON response
    return JsonResponse(context)


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

    # Get categories map to check counts_to_total flag
    categories_map = {cat.name: cat.counts_to_total for cat in Category.objects.filter(user=user)}

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
        # Convert to USD and group by source (keep sign: positive = expense, negative = income)
        source_totals = {}
        missing_rates_count = 0
        transactions = month_qs.select_related('source', 'category')

        for tx in transactions:
            # Skip transactions from categories that don't count to total
            cat_name = tx.category.name if tx.category else 'Sin categoría'
            counts_to_total = categories_map.get(cat_name, True)
            if not counts_to_total:
                continue

            src_name = tx.source.name
            amount_usd = tx.to_usd()

            if amount_usd is None:
                missing_rates_count += 1
                continue

            if src_name not in source_totals:
                source_totals[src_name] = Decimal('0')
            # Keep sign to calculate net spending (expenses minus income)
            source_totals[src_name] += amount_usd

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
        # Group by source AND currency (keep sign: positive = expense, negative = income)
        source_currency_totals = {}
        transactions = month_qs.select_related('source', 'category')

        for tx in transactions:
            # Skip transactions from categories that don't count to total
            cat_name = tx.category.name if tx.category else 'Sin categoría'
            counts_to_total = categories_map.get(cat_name, True)
            if not counts_to_total:
                continue

            src_name = tx.source.name
            currency = tx.currency
            key = (src_name, currency)

            if key not in source_currency_totals:
                source_currency_totals[key] = Decimal('0')
            # Keep sign to calculate net spending (expenses minus income)
            source_currency_totals[key] += tx.amount

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

    context = {
        'src_expenses': src_expenses,
        'selected_month_str': month_str(sel_year, sel_month),
        'm_current': month_str(current_year, current_month),
        'm_prev': month_str(py, pm),
        'convert_to_usd': convert_to_usd,
        'missing_rates': missing_rates,
    }

    # HTMX request - return HTML
    if request.htmx:
        return render(request, 'expenses/partials/source_expenses.html', context)

    # Legacy JSON response
    return JsonResponse(context)


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
    """Update user preference via AJAX/HTMX"""
    preference_key = request.POST.get('key')
    preference_value = request.POST.get('value')

    if preference_key == 'convert_expenses_to_usd':
        try:
            with transaction.atomic():
                # Get or create user preferences
                prefs, created = UserPreferences.objects.get_or_create(user=request.user)
                prefs.convert_expenses_to_usd = (preference_value == 'true')
                prefs.save()

            # HTMX request - return HTML fragment
            if request.htmx:
                return HttpResponse(
                    '<span style="color:#059669;background:#d1fae5;padding:0.25rem 0.5rem;'
                    'border-radius:3px;font-size:0.9rem">✓ Preferencia guardada</span>'
                )

            # Legacy JSON response
            return JsonResponse({
                'success': True,
                'message': 'Preference updated'
            })
        except Exception as e:
            # HTMX request - return error HTML
            if request.htmx:
                return HttpResponse(
                    f'<span style="color:#dc2626;background:#fee2e2;padding:0.25rem 0.5rem;'
                    f'border-radius:3px;font-size:0.9rem">Error: {str(e)}</span>',
                    status=500
                )

            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)

    # Invalid preference key
    if request.htmx:
        return HttpResponse(
            '<span style="color:#dc2626;background:#fee2e2;padding:0.25rem 0.5rem;'
            'border-radius:3px;font-size:0.9rem">Error: Preferencia inválida</span>',
            status=400
        )

    return JsonResponse({
        'success': False,
        'error': 'Invalid preference key'
    }, status=400)


# ============================================================================
# IMAGE UPLOAD VIEWS
# ============================================================================

@login_required
def image_upload_view(request):
    """Main view for uploading transaction images (receipts, invoices, etc)."""
    import uuid
    from .models import ImageUpload
    from .forms import ImageUploadForm

    context = _get_onboarding_context(request.user)

    if request.method == 'POST':
        # Get or create session ID
        session_id = request.POST.get('session_id') or str(uuid.uuid4())

        # Handle multiple files - Django handles this automatically
        images = request.FILES.getlist('images')

        if not images:
            messages.error(request, 'No se seleccionaron imágenes.')
            return redirect('expenses:image_upload')

        created_images = []
        for image_file in images:
            # Validate file type
            if not image_file.content_type.startswith('image/'):
                logger.warning(f"Skipping non-image file: {image_file.name}")
                continue

            # Create database record - Django uploads to storage automatically
            img = ImageUpload.objects.create(
                user=request.user,
                image=image_file,  # Django handles upload to Railway bucket or local media
                original_filename=image_file.name,
                session_id=session_id,
                status='pending'
            )
            created_images.append(img)

        logger.info(
            f"User {request.user.id} uploaded {len(created_images)} images, session {session_id}"
        )

        messages.success(
            request,
            f'Se subieron {len(created_images)} imagen(es). ¿Deseas agregar más o procesar ahora?'
        )

        # Redirect to preview page
        return redirect('expenses:image_preview', session_id=session_id)
    else:
        form = ImageUploadForm()

    context['form'] = form
    return render(request, 'expenses/image_upload.html', context)


@login_required
def image_preview_view(request, session_id):
    """Preview uploaded images before processing."""
    from .models import ImageUpload
    
    context = _get_onboarding_context(request.user)
    
    # Get all images for this session
    images = ImageUpload.objects.filter(
        user=request.user,
        session_id=session_id
    ).order_by('uploaded_at')
    
    if not images.exists():
        messages.error(request, 'No se encontraron imágenes para esta sesión.')
        return redirect('expenses:image_upload')
    
    context['images'] = images
    context['session_id'] = session_id
    context['pending_count'] = images.filter(status='pending').count()
    
    return render(request, 'expenses/image_preview.html', context)


@login_required
@require_POST
def image_delete_view(request, image_id):
    """Delete an uploaded image before processing."""
    from .models import ImageUpload
    
    try:
        import os
        
        image = get_object_or_404(ImageUpload, id=image_id, user=request.user)
        session_id = image.session_id
        
        # Can only delete pending images
        if image.status != 'pending':
            messages.error(request, 'No se puede eliminar una imagen ya procesada.')
            return redirect('expenses:image_preview', session_id=session_id)

        # Delete file from storage (Railway bucket or local filesystem)
        if image.image:
            image.image.delete(save=False)  # Delete file without saving model

        # Delete temp file (for legacy records with image_path)
        if image.image_path and os.path.exists(image.image_path):
            try:
                os.remove(image.image_path)
            except Exception as e:
                logger.warning(f"Failed to delete temp file {image.image_path}: {e}")

        image.delete()
        messages.success(request, 'Imagen eliminada.')
        
        # Check if there are more images in this session
        remaining = ImageUpload.objects.filter(
            user=request.user,
            session_id=session_id
        ).exists()
        
        if not remaining:
            return redirect('expenses:image_upload')
        
        return redirect('expenses:image_preview', session_id=session_id)
        
    except Exception as e:
        logger.error(f"Error deleting image {image_id}: {e}")
        messages.error(request, f'Error al eliminar la imagen: {str(e)}')
        return redirect('expenses:image_upload')


@login_required
@require_POST
def image_process_view(request, session_id):
    """Trigger Celery task to process images with LlamaCloud."""
    from .models import ImageUpload
    from .tasks import process_images_task
    
    # Verify session belongs to user
    images = ImageUpload.objects.filter(
        user=request.user,
        session_id=session_id,
        status='pending'
    )
    
    if not images.exists():
        messages.error(request, 'No hay imágenes pendientes para procesar.')
        return redirect('expenses:image_upload')
    
    # Trigger Celery task
    try:
        process_images_task.delay(session_id, request.user.id)
        messages.success(
            request,
            f'Se están procesando {images.count()} imagen(es). '
            'Te notificaremos cuando estén listas para revisar.'
        )
        logger.info(f"Started processing task for session {session_id}, user {request.user.id}")
    except Exception as e:
        logger.error(f"Error starting image processing task: {e}")
        messages.error(request, f'Error al iniciar el procesamiento: {str(e)}')
        return redirect('expenses:image_preview', session_id=session_id)
    
    return redirect('expenses:image_results', session_id=session_id)


@login_required
def image_results_view(request, session_id):
    """Show processing status and extracted transactions."""
    from .models import ImageUpload, Source, Category, Payee
    from decimal import Decimal

    context = _get_onboarding_context(request.user)
    
    images = ImageUpload.objects.filter(
        user=request.user,
        session_id=session_id
    ).order_by('uploaded_at')

    if not images.exists():
        messages.error(request, 'No se encontraron imágenes para esta sesión.')
        return redirect('expenses:image_upload')

    # Detect stalled processing (timeout after 10 minutes)
    from django.utils import timezone
    from datetime import timedelta

    timeout_threshold = timezone.now() - timedelta(minutes=10)
    stalled_images = images.filter(
        status='processing',
        uploaded_at__lt=timeout_threshold
    )

    if stalled_images.exists():
        stalled_count = stalled_images.update(
            status='failed',
            processing_error='Tiempo de procesamiento excedido - por favor reintente',
            processed_at=timezone.now()
        )
        logger.warning(f"Marked {stalled_count} stalled images as failed for session {session_id}")
        messages.warning(
            request,
            f'{stalled_count} imagen(es) excedieron el tiempo de procesamiento. '
            'Puedes reintentar el procesamiento.'
        )

    # Check status
    pending_count = images.filter(status='pending').count()
    processing_count = images.filter(status='processing').count()
    processed_count = images.filter(status='processed').count()
    failed_count = images.filter(status='failed').count()
    
    # Extract all transactions from processed images with duplicate detection
    all_transactions = []
    for img in images.filter(status='processed', extracted_data__isnull=False):
        extracted = img.extracted_data.get('transactions', [])
        for tx_data in extracted:
            tx_data['image_id'] = img.id
            tx_data['image_filename'] = img.original_filename

            # Check for exact duplicate (date + description + amount + currency)
            exact_duplicate = Transaction.objects.filter(
                user=request.user,
                date=tx_data['date'],
                description=tx_data['description'],
                amount=Decimal(str(tx_data['amount'])),
                currency=tx_data['currency'].upper()
            ).exists()

            # Check for partial duplicate (date + amount + currency, no description)
            partial_duplicate = False
            if not exact_duplicate:
                partial_duplicate = Transaction.objects.filter(
                    user=request.user,
                    date=tx_data['date'],
                    amount=Decimal(str(tx_data['amount'])),
                    currency=tx_data['currency'].upper()
                ).exists()

            tx_data['is_exact_duplicate'] = exact_duplicate
            tx_data['is_partial_duplicate'] = partial_duplicate
            all_transactions.append(tx_data)

    # Get user categories and payees for autocomplete
    user_categories = Category.objects.filter(user=request.user).values_list('name', flat=True).distinct()
    user_payees = Payee.objects.filter(user=request.user).values_list('name', flat=True).distinct()

    context.update({
        'session_id': session_id,
        'images': images,
        'pending_count': pending_count,
        'processing_count': processing_count,
        'processed_count': processed_count,
        'failed_count': failed_count,
        'transactions': all_transactions,
        'is_complete': pending_count == 0 and processing_count == 0,
        'has_failed': failed_count > 0,
        'sources': Source.objects.filter(user=request.user).order_by('name'),
        'user_categories': user_categories,
        'user_payees': user_payees,
    })

    return render(request, 'expenses/image_results.html', context)


@login_required
@require_POST
def image_confirm_transactions_view(request, session_id):
    """Create transactions from extracted image data."""
    from .models import ImageUpload, Transaction, Source, Category, Payee
    from decimal import Decimal
    import json
    
    try:
        # Get selected transaction indices from form
        selected_indices = request.POST.getlist('selected_transactions')
        source_name = request.POST.get('source_name', 'image_upload')
        
        if not selected_indices:
            messages.warning(request, 'No se seleccionaron transacciones.')
            return redirect('expenses:image_results', session_id=session_id)
        
        # Get all processed images for this session
        images = ImageUpload.objects.filter(
            user=request.user,
            session_id=session_id,
            status='processed',
            extracted_data__isnull=False
        )
        
        # Collect all transactions
        all_transactions = []
        for img in images:
            extracted = img.extracted_data.get('transactions', [])
            for tx_data in extracted:
                tx_data['image_id'] = img.id
                all_transactions.append(tx_data)
        
        # Get or create source
        source, _ = Source.objects.get_or_create(
            user=request.user,
            name=source_name
        )
        
        created_count = 0
        duplicate_count = 0
        
        with transaction.atomic():
            for idx_str in selected_indices:
                idx = int(idx_str)
                if idx >= len(all_transactions):
                    continue
                
                tx_data = all_transactions[idx]
                
                # Get currency override (if user changed it)
                currency_override = request.POST.get(f'currency_{idx}')
                if currency_override:
                    tx_data['currency'] = currency_override
                
                # Check if sign should be flipped
                flip_sign = request.POST.get(f'flip_{idx}')
                amount = Decimal(str(tx_data['amount']))
                if flip_sign:
                    amount = -amount

                # Get optional category and payee
                category_name = request.POST.get(f'category_{idx}', '').strip()
                payee_name = request.POST.get(f'payee_{idx}', '').strip()
                notes = request.POST.get(f'notes_{idx}', '').strip()

                # Check for duplicates (use the potentially flipped amount and currency)
                existing = Transaction.objects.filter(
                    user=request.user,
                    date=tx_data['date'],
                    amount=amount,
                    description=tx_data['description'],
                    currency=tx_data['currency'].upper()
                ).exists()

                if existing:
                    duplicate_count += 1
                    logger.warning(f"Duplicate transaction from image: {tx_data}")
                    continue

                # Get or create category if provided
                category = None
                if category_name:
                    category, _ = Category.objects.get_or_create(
                        user=request.user,
                        name=category_name
                    )

                # Get or create payee if provided
                payee = None
                if payee_name:
                    payee, _ = Payee.objects.get_or_create(
                        user=request.user,
                        name=payee_name
                    )

                # Create transaction with all fields
                tx = Transaction.objects.create(
                    user=request.user,
                    date=tx_data['date'],
                    description=tx_data['description'],
                    amount=amount,
                    currency=tx_data['currency'].upper(),
                    source=source,
                    category=category,
                    payee=payee,
                    notes=notes if notes else None,
                    status='confirmed'
                )

                created_count += 1
        
        if created_count > 0:
            messages.success(
                request,
                f'Se crearon {created_count} transacción(es) exitosamente.'
            )
        
        if duplicate_count > 0:
            messages.warning(
                request,
                f'{duplicate_count} transacción(es) duplicadas no se agregaron.'
            )
        
        logger.info(
            f"User {request.user.id} created {created_count} transactions from images, "
            f"session {session_id}"
        )
        
        return redirect('profile')
        
    except Exception as e:
        logger.error(f"Error confirming transactions from images: {e}", exc_info=True)
        messages.error(request, f'Error al crear transacciones: {str(e)}')
        return redirect('expenses:image_results', session_id=session_id)


@login_required
@require_POST
def api_check_duplicate(request):
    """
    API endpoint to check if a transaction is a duplicate.
    Returns both exact and partial duplicate status.
    """
    import json
    from decimal import Decimal

    try:
        data = json.loads(request.body)
        date = data.get('date')
        description = data.get('description')
        amount = Decimal(str(data.get('amount')))
        currency = data.get('currency', '').upper()

        # Check for exact duplicate (date + description + amount + currency)
        exact_duplicate = Transaction.objects.filter(
            user=request.user,
            date=date,
            description=description,
            amount=amount,
            currency=currency
        ).exists()

        # Check for partial duplicate (date + amount + currency, no description)
        partial_duplicate = False
        if not exact_duplicate:
            partial_duplicate = Transaction.objects.filter(
                user=request.user,
                date=date,
                amount=amount,
                currency=currency
            ).exists()

        return JsonResponse({
            'is_exact_duplicate': exact_duplicate,
            'is_partial_duplicate': partial_duplicate
        })

    except Exception as e:
        logger.error(f"Error checking duplicate: {e}", exc_info=True)
        return JsonResponse({
            'is_exact_duplicate': False,
            'is_partial_duplicate': False,
            'error': str(e)
        }, status=400)


@login_required
def my_uploads_view(request):
    """Show user's recent upload sessions for recovery."""
    from .models import ImageUpload
    from django.db.models import Count, Max, Min, Q

    context = _get_onboarding_context(request.user)

    # Get all sessions from the last 30 days
    from django.utils import timezone
    from datetime import timedelta

    threshold = timezone.now() - timedelta(days=30)

    # Group images by session_id with aggregate stats
    sessions = ImageUpload.objects.filter(
        user=request.user,
        uploaded_at__gte=threshold
    ).values('session_id').annotate(
        image_count=Count('id'),
        first_upload=Min('uploaded_at'),
        last_updated=Max('uploaded_at'),
        pending_count=Count('id', filter=Q(status='pending')),
        processing_count=Count('id', filter=Q(status='processing')),
        processed_count=Count('id', filter=Q(status='processed')),
        failed_count=Count('id', filter=Q(status='failed'))
    ).order_by('-last_updated')

    # Add session status for each
    for session in sessions:
        if session['processing_count'] > 0:
            session['status'] = 'processing'
            session['status_display'] = 'En proceso'
            session['status_class'] = 'warning'
        elif session['pending_count'] > 0:
            session['status'] = 'pending'
            session['status_display'] = 'Pendiente'
            session['status_class'] = 'info'
        elif session['failed_count'] > 0 and session['processed_count'] == 0:
            session['status'] = 'failed'
            session['status_display'] = 'Fallido'
            session['status_class'] = 'danger'
        elif session['failed_count'] > 0:
            session['status'] = 'partial'
            session['status_display'] = 'Parcial'
            session['status_class'] = 'warning'
        else:
            session['status'] = 'completed'
            session['status_display'] = 'Completado'
            session['status_class'] = 'success'

    context['sessions'] = sessions
    context['total_sessions'] = len(sessions)

    return render(request, 'expenses/my_uploads.html', context)


@login_required
@require_POST
def retry_processing_view(request, session_id):
    """Retry processing for failed/stalled uploads."""
    from .models import ImageUpload
    from .tasks import process_images_task

    try:
        # Get failed or stalled images for this session
        images = ImageUpload.objects.filter(
            user=request.user,
            session_id=session_id,
            status__in=['failed', 'processing']
        )

        if not images.exists():
            messages.warning(request, 'No hay imágenes fallidas o estancadas para reintentar.')
            return redirect('expenses:image_results', session_id=session_id)

        # Reset status to pending
        count = images.update(
            status='pending',
            processing_error='',
            processed_at=None,
            extracted_data=None
        )

        # Trigger Celery task
        process_images_task.delay(session_id, request.user.id)

        messages.success(
            request,
            f'Se reintentará el procesamiento de {count} imagen(es).'
        )
        logger.info(f"User {request.user.id} retrying processing for session {session_id}, {count} images")

        return redirect('expenses:image_results', session_id=session_id)

    except Exception as e:
        logger.error(f"Error retrying processing for session {session_id}: {e}", exc_info=True)
        messages.error(request, f'Error al reintentar: {str(e)}')
        return redirect('expenses:image_results', session_id=session_id)


@login_required
@require_POST
def reject_session_view(request, session_id):
    """Reject/discard all images in an upload session."""
    from .models import ImageUpload

    try:
        images = ImageUpload.objects.filter(
            user=request.user,
            session_id=session_id
        )

        if not images.exists():
            messages.warning(request, 'No se encontraron imágenes para esta sesión.')
            return redirect('expenses:image_upload')

        # Delete uploaded files from storage
        for img in images:
            if img.image:
                try:
                    img.image.delete(save=False)
                except Exception as e:
                    logger.warning(f"Failed to delete image file {img.id}: {e}")

        # Delete database records
        count = images.count()
        images.delete()

        messages.success(
            request,
            f'Se descartaron {count} imagen(es) y sus datos extraídos.'
        )
        logger.info(f"User {request.user.id} rejected session {session_id}, {count} images deleted")

        return redirect('expenses:image_upload')

    except Exception as e:
        logger.error(f"Error rejecting session {session_id}: {e}", exc_info=True)
        messages.error(request, f'Error al rechazar sesión: {str(e)}')
        return redirect('expenses:image_results', session_id=session_id)
