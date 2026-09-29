from django.urls import path
from django.views.generic import RedirectView

from . import auth_views, manage_views, staff_views, views

app_name = 'kahawa'

urlpatterns = [
    path('', views.home, name='home'),
    path('menu/', views.product_list, name='menu'),
    path('cart/', views.cart, name='cart'),
    path('privacy/', views.privacy, name='privacy'),
    path('terms/', views.terms, name='terms'),
    path('allergens/', views.allergens, name='allergens'),
    path('orders/', views.orders, name='orders'),
    path('orders/by-codes/', views.orders_by_codes, name='orders_by_codes'),
    path(
        'orders/<str:order_code>/reorder-data/',
        views.reorder_data,
        name='reorder_data',
    ),
    path(
        'orders/<str:order_code>/reorder/',
        views.reorder,
        name='reorder',
    ),
    path(
        'orders/<str:order_code>/receipt/',
        views.order_receipt,
        name='order_receipt',
    ),
    path('orders/<str:order_code>/', views.order_detail, name='order_detail'),
    path('track/', views.track_order, name='track_order'),
    path('my-orders/', views.my_orders, name='my_orders'),
    path('checkout/', views.checkout, name='checkout'),
    path('checkout/place-order/', views.place_order, name='place_order'),
    path('checkout/start-payment/', views.start_payment, name='start_payment'),
    path(
        'checkout/payment-status/<str:order_code>/',
        views.payment_status,
        name='payment_status',
    ),
    path(
        'checkout/confirmation/<str:order_code>/',
        views.order_confirmation,
        name='order_confirmation',
    ),
    path('mpesa/callback/', views.mpesa_callback, name='mpesa_callback'),
    path(
        'mpesa/callback/<str:secret>/',
        views.mpesa_callback_secure,
        name='mpesa_callback_secure',
    ),
    path('t/<slug:code>/', views.table_entry, name='table_entry'),
    path('cart/clear-table/', views.clear_table, name='clear_table'),
    path('gift-cards/', views.gift_card_buy, name='gift_card_buy'),
    path(
        'gift-cards/<str:code>/pending/',
        views.gift_card_pending,
        name='gift_card_pending',
    ),
    path(
        'gift-cards/<str:code>/status/',
        views.gift_card_status,
        name='gift_card_status',
    ),
    path(
        'gift-cards/<str:code>/retry/',
        views.gift_card_retry,
        name='gift_card_retry',
    ),
    path(
        'gift-cards/<str:code>/',
        views.gift_card_success,
        name='gift_card_success',
    ),
    path('accounts/login/', auth_views.login_view, name='login'),
    path('accounts/register/', auth_views.register_view, name='register'),
    path(
        'accounts/register/verify/',
        auth_views.register_verify_view,
        name='register_verify',
    ),
    path(
        'accounts/password-reset/',
        auth_views.password_reset_request_view,
        name='password_reset',
    ),
    path(
        'accounts/password-reset/verify/',
        auth_views.password_reset_verify_view,
        name='password_reset_verify',
    ),
    path('accounts/profile/', auth_views.profile_view, name='profile'),
    path('logout/', auth_views.logout_view, name='logout'),
    # ── Cafe management (/manage) — admin + staff entry ─────────────────
    path('manage/', manage_views.manage_entry, name='manage_entry'),
    path('manage/login/', manage_views.staff_login, name='staff_login'),
    path('manage/logout/', manage_views.staff_logout, name='staff_logout'),
    path('manage/ops/', staff_views.staff_dashboard, name='staff_dashboard'),
    path(
        'manage/day/',
        RedirectView.as_view(pattern_name='kahawa:sales_history', query_string=True),
        name='end_of_day',
    ),
    path('manage/sales/', staff_views.sales_history, name='sales_history'),
    path('manage/sales/pdf/', staff_views.sales_pdf, name='sales_pdf'),
    path(
        'manage/orders/<str:order_code>/kitchen/',
        staff_views.kitchen_ticket,
        name='kitchen_ticket',
    ),
    path(
        'manage/api/live-orders/',
        staff_views.live_orders_api,
        name='staff_live_orders',
    ),
    path(
        'manage/api/orders/<int:order_id>/status/',
        staff_views.update_order_status,
        name='staff_update_status',
    ),
    path(
        'manage/api/orders/<int:order_id>/collect/',
        staff_views.collect_order_payment,
        name='staff_collect_payment',
    ),
    path(
        'manage/api/orders/create/',
        staff_views.create_counter_order,
        name='staff_create_order',
    ),
    path('manage/products/', manage_views.manage_products, name='manage_products'),
    path(
        'manage/products/new/',
        manage_views.product_edit,
        name='manage_product_new',
    ),
    path(
        'manage/products/<int:product_id>/',
        manage_views.product_edit,
        name='manage_product_edit',
    ),
    path(
        'manage/products/<int:product_id>/toggle/',
        manage_views.product_toggle_available,
        name='product_toggle_available',
    ),
    path(
        'manage/products/<int:product_id>/delete/',
        manage_views.product_delete,
        name='manage_product_delete',
    ),
    path(
        'manage/categories/',
        manage_views.manage_categories,
        name='manage_categories',
    ),
    path('manage/packages/', manage_views.manage_packages, name='manage_packages'),
    path('manage/tables/', manage_views.manage_tables, name='manage_tables'),
    path(
        'manage/gift-cards/',
        manage_views.manage_gift_cards,
        name='manage_gift_cards',
    ),
    path(
        'manage/api/gift-cards/<int:gift_id>/collect/',
        manage_views.collect_gift_payment,
        name='manage_collect_gift_payment',
    ),
    path('manage/team/', manage_views.manage_team, name='manage_team'),
    path(
        'manage/team/<int:profile_id>/activity/',
        manage_views.manage_team_activity,
        name='manage_team_activity',
    ),
    # Legacy /staff/* → /manage/*
    path(
        'staff/',
        RedirectView.as_view(pattern_name='kahawa:manage_entry', permanent=False),
    ),
    path(
        'staff/login/',
        RedirectView.as_view(pattern_name='kahawa:staff_login', permanent=False),
    ),
    path(
        'staff/dashboard/',
        RedirectView.as_view(pattern_name='kahawa:staff_dashboard', permanent=False),
    ),
    path(
        'staff/<path:rest>',
        RedirectView.as_view(url='/manage/', permanent=False),
    ),
]
