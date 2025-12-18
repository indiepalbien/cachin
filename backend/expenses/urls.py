from django.urls import path

from . import views

app_name = "expenses"
urlpatterns = [
    # Management dashboard and CRUD routes for finance models
    path("manage/", views.manage_dashboard, name="manage_dashboard"),
    path("manage/categorizar/", views.categorize_transactions, name="categorize_transactions"),
    path("manage/category-transactions/", views.edit_category_transactions, name="edit_category_transactions"),
    path("manage/categories/", views.CategoryListView.as_view(), name="manage_categories"),
    path("manage/categories/add/", views.CategoryCreateView.as_view(), name="manage_category_add"),
    path("manage/categories/<int:pk>/edit/", views.CategoryUpdateView.as_view(), name="manage_category_edit"),
    path("manage/categories/<int:pk>/delete/", views.CategoryDeleteView.as_view(), name="manage_category_delete"),

    path("manage/projects/", views.ProjectListView.as_view(), name="manage_projects"),
    path("manage/projects/add/", views.ProjectCreateView.as_view(), name="manage_project_add"),
    path("manage/projects/<int:pk>/edit/", views.ProjectUpdateView.as_view(), name="manage_project_edit"),
    path("manage/projects/<int:pk>/delete/", views.ProjectDeleteView.as_view(), name="manage_project_delete"),

    path("manage/payees/", views.PayeeListView.as_view(), name="manage_payees"),
    path("manage/payees/add/", views.PayeeCreateView.as_view(), name="manage_payee_add"),
    path("manage/payees/<int:pk>/edit/", views.PayeeUpdateView.as_view(), name="manage_payee_edit"),
    path("manage/payees/<int:pk>/delete/", views.PayeeDeleteView.as_view(), name="manage_payee_delete"),

    path("manage/sources/", views.SourceListView.as_view(), name="manage_sources"),
    path("manage/sources/add/", views.SourceCreateView.as_view(), name="manage_source_add"),
    path("manage/sources/<int:pk>/edit/", views.SourceUpdateView.as_view(), name="manage_source_edit"),
    path("manage/sources/<int:pk>/delete/", views.SourceDeleteView.as_view(), name="manage_source_delete"),

    path("manage/exchanges/", views.ExchangeListView.as_view(), name="manage_exchanges"),
    path("manage/exchanges/add/", views.ExchangeCreateView.as_view(), name="manage_exchange_add"),
    path("manage/exchanges/<int:pk>/edit/", views.ExchangeUpdateView.as_view(), name="manage_exchange_edit"),
    path("manage/exchanges/<int:pk>/delete/", views.ExchangeDeleteView.as_view(), name="manage_exchange_delete"),

    path("manage/balances/", views.BalanceListView.as_view(), name="manage_balances"),
    path("manage/balances/add/", views.BalanceCreateView.as_view(), name="manage_balance_add"),
    path("manage/balances/<int:pk>/edit/", views.BalanceUpdateView.as_view(), name="manage_balance_edit"),
    path("manage/balances/<int:pk>/delete/", views.BalanceDeleteView.as_view(), name="manage_balance_delete"),

    path("manage/transactions/", views.TransactionListView.as_view(), name="manage_transactions"),
    path("manage/transactions/add/", views.TransactionCreateView.as_view(), name="manage_transaction_add"),
    path("manage/transactions/<int:pk>/edit/", views.TransactionUpdateView.as_view(), name="manage_transaction_edit"),
    path("manage/transactions/<int:pk>/delete/", views.TransactionDeleteView.as_view(), name="manage_transaction_delete"),
    
    # Emails
    path("manage/emails/", views.EmailMessageListView.as_view(), name="manage_emails"),
    path("manage/emails/update-forwarding/", views.update_forwarding_email, name="update_forwarding_email"),
    # Pending Transactions
    path("manage/pending/", views.PendingTransactionListView.as_view(), name="manage_pending_transactions"),
    # Quick-add transaction (AJAX-friendly) and suggestion endpoints
    path("quick-transaction/", views.quick_transaction, name="quick_transaction"),
    path("suggest/<str:kind>/", views.suggest, name="suggest"),
    
    # Bulk transaction import
    path("bulk-add/", views.bulk_add_view, name="bulk_add"),
    path("bulk-add/parse/", views.bulk_parse_view, name="bulk_parse"),
    path("bulk-add/confirm/", views.bulk_confirm_view, name="bulk_confirm"),

    path("manage/splitwise/", views.splitwise_status, name="splitwise_status"),
    path('splitwise/connect/', views.splitwise_connect, name='splitwise_connect'),
    path('splitwise/callback/', views.splitwise_callback, name='splitwise_callback'),
    
    # API endpoints for async loading
    path("api/recent-transactions/", views.api_recent_transactions, name="api_recent_transactions"),
    path("api/category-expenses/", views.api_category_expenses, name="api_category_expenses"),
    path("api/update-preference/", views.update_user_preference, name="update_user_preference"),
]