from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline
from django.http import HttpResponseRedirect
from django.urls import path
from django.shortcuts import render
from .models import (
    UserProfile, Product, Category, Collection, Image, Video,
    Translation, CurrencyRate, Inquiry, InquiryReply, Order, OrderItem,
    SiteBanner, Review
)
from .translation_utils import translate_product_to_all_languages
from .email_utils import send_inquiry_confirmation, send_order_payment_link_email
from datetime import timedelta
from django.utils import timezone
from django.conf import settings


class TranslationInline(GenericTabularInline):
    model = Translation
    extra = 0
    fields = ('language_code', 'field_name', 'translated_text')
    readonly_fields = ('field_name',)

class ImageInline(admin.TabularInline):
    model = Image
    extra = 1

class VideoInline(admin.TabularInline):
    model = Video
    extra = 1

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('title', 'sku', 'price_inr', 'price_usd', 'is_featured', 'is_active', 'created_at')
    list_filter = ('is_active', 'category', 'collection')
    search_fields = ('title', 'sku', 'description')
    prepopulated_fields = {'slug': ('title',)}
    inlines = [ImageInline, VideoInline, TranslationInline]
    actions = ['translate_selected_products']

    def translate_selected_products(self, request, queryset):
        """Admin action to translate selected products."""
        count = 0
        for product in queryset:
            try:
                translate_product_to_all_languages(product)
                count += 1
            except Exception as e:
                self.message_user(request, f"Error translating {product.title}: {str(e)}", level='ERROR')
        if count:
            self.message_user(request, f"Successfully translated {count} product(s).")
    translate_selected_products.short_description = "Translate selected products to all languages"

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    prepopulated_fields = {'slug': ('name',)}
    inlines = [TranslationInline]
    actions = ['translate_selected_categories']

    def translate_selected_categories(self, request, queryset):
        from .translation_utils import translate_category_to_all_languages
        for cat in queryset:
            translate_category_to_all_languages(cat)
        self.message_user(request, f"Translated {queryset.count()} categories.")
    translate_selected_categories.short_description = "Translate selected categories"

@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    prepopulated_fields = {'slug': ('name',)}
    inlines = [TranslationInline]
    actions = ['translate_selected_collections']

    def translate_selected_collections(self, request, queryset):
        from .translation_utils import translate_collection_to_all_languages
        for coll in queryset:
            translate_collection_to_all_languages(coll)
        self.message_user(request, f"Translated {queryset.count()} collections.")
    translate_selected_collections.short_description = "Translate selected collections"

@admin.register(CurrencyRate)
class CurrencyRateAdmin(admin.ModelAdmin):
    list_display = ('currency_code', 'rate_to_usd', 'updated_at')
    list_editable = ('rate_to_usd',)

class InquiryReplyInline(admin.TabularInline):
    model = InquiryReply
    extra = 1
    fields = ('message', 'sent_by_admin')
    readonly_fields = ('created_at',)

    def formfield_for_dbfield(self, db_field, **kwargs):
        field = super().formfield_for_dbfield(db_field, **kwargs)
        if db_field.name == 'message':
            field.widget = admin.widgets.AdminTextareaWidget(attrs={'rows': 4, 'cols': 60})
        return field

@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    list_display = ('customer_name', 'email', 'product', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('customer_name', 'email', 'product__title')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [InquiryReplyInline]
    actions = ['mark_contacted', 'mark_quotation_sent', 'send_test_email']

    def mark_contacted(self, request, queryset):
        queryset.update(status='contacted')
        self.message_user(request, "Selected inquiries marked as Contacted.")
    mark_contacted.short_description = "Mark as Contacted"

    def mark_quotation_sent(self, request, queryset):
        queryset.update(status='quotation_sent')
        self.message_user(request, "Selected inquiries marked as Quotation Sent.")
    mark_quotation_sent.short_description = "Mark as Quotation Sent"

    def send_test_email(self, request, queryset):
        """Send a test email to the first selected inquiry's customer."""
        for inquiry in queryset[:1]:
            send_inquiry_confirmation(inquiry)
            self.message_user(request, f"Test email sent to {inquiry.email}")
    send_test_email.short_description = "Send confirmation email (test)"


admin.site.register(Translation)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'is_email_verified')
    search_fields = ('user__email', 'user__username', 'phone')


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ('product_title', 'sku', 'unit_price', 'quantity', 'total_price')
    readonly_fields = ('total_price',)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number', 'customer_name', 'email', 'currency',
        'total_amount', 'status', 'payment_link_expires_at', 'created_at'
    )
    list_filter = ('status', 'currency', 'country', 'created_at')
    search_fields = ('order_number', 'customer_name', 'email', 'phone')
    readonly_fields = (
        'order_number', 'payment_token', 'created_at', 'updated_at',
        'subtotal_amount', 'total_amount'
    )
    inlines = [OrderItemInline]
    actions = ['resend_payment_link', 'extend_24_hours', 'mark_paid']

    def resend_payment_link(self, request, queryset):
        count = 0
        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000').rstrip('/')
        for order in queryset:
            payment_url = f"{frontend_url}/pay/{order.payment_token}"
            send_order_payment_link_email(order, payment_url)
            count += 1
        self.message_user(request, f"Resent 24-hour payment link to {count} order(s).")
    resend_payment_link.short_description = "Resend 24-hour payment link email"

    def extend_24_hours(self, request, queryset):
        for order in queryset:
            order.payment_link_expires_at = timezone.now() + timedelta(hours=24)
            if order.status == 'expired':
                order.status = 'pending_payment'
            order.save(update_fields=['payment_link_expires_at', 'status'])
        self.message_user(request, f"Extended payment link by 24 hours for {queryset.count()} order(s).")
    extend_24_hours.short_description = "Extend 24-hour window from now"

    def mark_paid(self, request, queryset):
        queryset.update(status='paid')
        self.message_user(request, f"Marked {queryset.count()} order(s) as Paid.")
    mark_paid.short_description = "Mark selected orders as Paid"


@admin.register(SiteBanner)
class SiteBannerAdmin(admin.ModelAdmin):
    list_display = ('title', 'is_active', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('title', 'subtitle', 'tagline')


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('product', 'customer_name', 'rating', 'is_verified_purchase', 'is_approved', 'is_featured_home', 'created_at')
    list_filter = ('rating', 'is_approved', 'is_featured_home', 'is_verified_purchase', 'created_at')
    search_fields = ('customer_name', 'customer_email', 'title', 'comment', 'product__title')
    actions = ['approve_reviews', 'feature_on_home', 'unfeature_from_home']

    def approve_reviews(self, request, queryset):
        queryset.update(is_approved=True)
        self.message_user(request, f"Approved {queryset.count()} reviews.")
    approve_reviews.short_description = "Approve selected reviews"

    def feature_on_home(self, request, queryset):
        queryset.update(is_featured_home=True, is_approved=True)
        self.message_user(request, f"Featured {queryset.count()} reviews on homepage.")
    feature_on_home.short_description = "Feature selected reviews on homepage"

    def unfeature_from_home(self, request, queryset):
        queryset.update(is_featured_home=False)
        self.message_user(request, f"Removed {queryset.count()} reviews from homepage.")
    unfeature_from_home.short_description = "Remove selected reviews from homepage"
