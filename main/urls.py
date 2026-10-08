from django.urls import path
from . import views
from . import order_views
from . import admin_api_views
from . import review_views

urlpatterns = [
    # Auth endpoints
    path('register/', views.RegisterView.as_view(), name='register'),
    path('verify-otp/', views.OTPVerifyView.as_view(), name='verify-otp'),
    path('resend-otp/', views.ResendOTPView.as_view(), name='resend-otp'),
    path('auth/request-otp/', order_views.EmailOTPRequestLoginView.as_view(), name='auth-request-otp'),
    path('auth/verify-otp-login/', order_views.EmailOTPVerifyLoginView.as_view(), name='auth-verify-otp-login'),
    path('auth/login-password/', order_views.EmailPasswordLoginView.as_view(), name='auth-login-password'),
    path('auth/me/', order_views.CurrentUserView.as_view(), name='auth-me'),

    # Product & Catalog endpoints
    path('products/featured/', views.FeaturedProductList.as_view(), name='featured-products'),
    path('products/', views.ProductList.as_view(), name='product-list'),
    path('products/<slug:slug>/reviews/', review_views.ProductReviewsView.as_view(), name='product-reviews'),
    path('products/<slug:slug>/can-review/', review_views.CheckReviewEligibilityView.as_view(), name='product-can-review'),
    path('products/<slug:slug>/view/', review_views.ProductRecordViewAPIView.as_view(), name='product-record-view'),
    path('products/<slug:slug>/', views.ProductDetail.as_view(), name='product-detail'),
    path('reviews/featured/', review_views.FeaturedReviewsView.as_view(), name='featured-reviews'),
    path('categories/', views.CategoryList.as_view(), name='category-list'),
    path('collections/', views.CollectionList.as_view(), name='collection-list'),
    path('currency-rates/', views.currency_rates, name='currency-rates'),
    path('inquiries/', views.create_inquiry, name='create-inquiry'),
    path('translate/', views.TranslateProxyView.as_view(), name='translate-proxy'),
    path('site-banners/', views.SiteBannerView.as_view(), name='site-banner'),

    # Orders & 24-Hour Payment Link Flow
    path('orders/', order_views.CreateOrderView.as_view(), name='create-order'),
    path('orders/pay/<uuid:token>/', order_views.OrderDetailByTokenView.as_view(), name='order-pay-detail'),
    path('orders/pay/<uuid:token>/initiate/', order_views.InitiatePaymentView.as_view(), name='order-pay-initiate'),
    path('orders/pay/<uuid:token>/verify/', order_views.VerifyPaymentView.as_view(), name='order-pay-verify'),
    path('orders/pay/<uuid:token>/request-cancel/', order_views.CustomerCancelRequestView.as_view(), name='order-request-cancel'),
    path('orders/my-orders/', order_views.UserOrdersView.as_view(), name='my-orders'),

    # Admin Portal Endpoints (Staff/Superuser Only)
    path('admin/stats/', admin_api_views.AdminDashboardStatsView.as_view(), name='admin-stats'),
    path('admin/products/', admin_api_views.AdminProductListView.as_view(), name='admin-products'),
    path('admin/products/<int:pk>/', admin_api_views.AdminProductDetailView.as_view(), name='admin-product-detail'),
    path('admin/products/<int:pk>/upload-image/', admin_api_views.AdminProductImageUploadView.as_view(), name='admin-product-image'),
    path('admin/products/<int:pk>/upload-video/', admin_api_views.AdminProductVideoUploadView.as_view(), name='admin-product-video'),
    path('admin/categories/', admin_api_views.AdminCategoryListView.as_view(), name='admin-categories'),
    path('admin/categories/<int:pk>/', admin_api_views.AdminCategoryDetailView.as_view(), name='admin-category-detail'),
    path('admin/collections/', admin_api_views.AdminCollectionListView.as_view(), name='admin-collections'),
    path('admin/collections/<int:pk>/', admin_api_views.AdminCollectionDetailView.as_view(), name='admin-collection-detail'),
    path('admin/orders/', admin_api_views.AdminOrderListView.as_view(), name='admin-orders'),
    path('admin/orders/<int:pk>/', admin_api_views.AdminOrderDetailView.as_view(), name='admin-order-detail'),
    path('admin/orders/<int:pk>/resend-link/', admin_api_views.AdminOrderResendLinkView.as_view(), name='admin-order-resend-link'),
    path('admin/orders/<int:pk>/process-refund/', admin_api_views.AdminOrderProcessRefundView.as_view(), name='admin-order-process-refund'),
    path('admin/orders/<int:pk>/reject-cancel/', admin_api_views.AdminOrderRejectCancelView.as_view(), name='admin-order-reject-cancel'),
    path('admin/inquiries/', admin_api_views.AdminInquiryListView.as_view(), name='admin-inquiries'),
    path('admin/inquiries/<int:pk>/', admin_api_views.AdminInquiryDetailView.as_view(), name='admin-inquiry-detail'),
    path('admin/inquiries/<int:pk>/reply/', admin_api_views.AdminInquiryReplyView.as_view(), name='admin-inquiry-reply'),
    path('admin/currency/refresh/', admin_api_views.AdminCurrencyRefreshView.as_view(), name='admin-currency-refresh'),
    path('admin/site-banner/', admin_api_views.AdminSiteBannerView.as_view(), name='admin-site-banner'),
    path('admin/site-banner/reset-media/', admin_api_views.AdminSiteBannerMediaResetView.as_view(), name='admin-site-banner-reset-media'),
]