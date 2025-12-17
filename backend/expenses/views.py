# Create your views here.
from django.http import HttpResponse, HttpResponseRedirect, Http404, JsonResponse
from django.template import loader
from django.shortcuts import get_object_or_404, render, redirect
from django.views import generic
from django.urls import reverse
from django.conf import settings
from django.db.models import F
from django.utils import timezone
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from .models import Category, Project, Payee, Source, Exchange, Balance, Transaction, UserEmailMessage, UserEmailConfig, PendingTransaction, SplitwiseAccount
from . import forms
from django.views.decorators.http import require_POST, require_GET
from django.utils import timezone as dj_timezone
from decimal import Decimal, InvalidOperation
import datetime
import requests
from requests_oauthlib import OAuth1Session
from django.core.paginator import Paginator
import logging

logger = logging.getLogger(__name__)

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
        ("Categories", "expenses:manage_categories"),
        ("Projects", "expenses:manage_projects"),
        ("Payees", "expenses:manage_payees"),
        ("Sources", "expenses:manage_sources"),
        ("Exchanges", "expenses:manage_exchanges"),
        ("Balances", "expenses:manage_balances"),
        ("Transactions", "expenses:manage_transactions"),
        ("Emails", "expenses:manage_emails"),
        ("Pending", "expenses:manage_pending_transactions"),
    ]
    return render(request, "manage/dashboard.html", {"resources": resources})


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
    template_name = "manage/list.html"


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
    categories = Category.objects.filter(user=user).order_by('name').values_list('name', flat=True)
    projects = Project.objects.filter(user=user).order_by('name').values_list('name', flat=True)
    payees = Payee.objects.filter(user=user).order_by('name').values_list('name', flat=True)
    sources = Source.objects.filter(user=user).order_by('name').values_list('name', flat=True)
    # Latest transactions (newest first) with pagination (5 per page)
    tx_qs = Transaction.objects.filter(user=user).order_by('-date', '-id')
    page_number = request.GET.get('page') or 1
    paginator = Paginator(tx_qs, 5)
    tx_page = paginator.get_page(page_number)

    # Monthly expenses by category in USD (current or previous month)
    today = datetime.date.today()
    current_year, current_month = today.year, today.month
    def month_str(y, m):
        return f"{y:04d}-{m:02d}"
    def prev_month(y, m):
        return (y-1, 12) if m == 1 else (y, m-1)
    def next_month(y, m):
        return (y+1, 1) if m == 12 else (y, m+1)
    selected_m = request.GET.get('m')
    sel_year, sel_month = current_year, current_month
    if selected_m:
        try:
            parts = selected_m.split('-')
            y = int(parts[0]); m = int(parts[1])
            if 1 <= m <= 12:
                sel_year, sel_month = y, m
        except Exception:
            sel_year, sel_month = current_year, current_month
    # Range: [first day of selected month, first day of next month)
    first_day = datetime.date(sel_year, sel_month, 1)
    ny, nm = next_month(sel_year, sel_month)
    next_first = datetime.date(ny, nm, 1)
    month_qs = Transaction.objects.filter(user=user, date__gte=first_day, date__lt=next_first)
    totals = {}
    missing_rates = 0
    for t in month_qs:
        # Consider expenses only (positive amounts; quick-add typically uses positive for outflows)
        if t.amount <= 0:
            continue
        usd = t.to_usd()
        if usd is None:
            missing_rates += 1
            continue
        key = t.category.name if t.category else 'Sin categoría'
        totals[key] = totals.get(key, Decimal('0')) + usd
    cat_expenses = [
        {
            'name': k,
            'total_usd': v,
        }
        for k, v in totals.items()
    ]
    cat_expenses.sort(key=lambda r: r['total_usd'], reverse=True)
    py, pm = prev_month(sel_year, sel_month)
    context_month = {
        'cat_expenses': cat_expenses,
        'selected_month_str': month_str(sel_year, sel_month),
        'm_current': month_str(current_year, current_month),
        'm_prev': month_str(py, pm),
        'exp_missing_rates': missing_rates,
    }
    context = {
        'user': user,
        'qa_categories': list(categories),
        'qa_projects': list(projects),
        'qa_payees': list(payees),
        'qa_sources': list(sources),
        'tx_page': tx_page,
        'tx_paginator': paginator,
        **context_month,
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
                    # Parse source string (e.g., "itau:7654" -> "7654")
                    source_name = txn["source"].split(":")[-1] if ":" in txn["source"] else txn["source"]
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

    account, _ = SplitwiseAccount.objects.get_or_create(user=request.user)
    account.oauth_token = access_token
    account.oauth_token_secret = access_secret
    if split_user_id:
        account.splitwise_user_id = split_user_id
    if raw:
        account.raw = raw
    account.save()
    return redirect(request.GET.get('next') or '/')