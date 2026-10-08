import uuid
from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _
from django.conf import settings
import random
import string
import urllib.parse
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


# ---------- NEW UserProfile model ----------
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone = models.CharField(max_length=15, blank=True, null=True)
    # OTP fields (for verification)
    otp = models.CharField(max_length=6, blank=True, null=True)
    otp_created_at = models.DateTimeField(blank=True, null=True)
    is_email_verified = models.BooleanField(default=False)

    def __str__(self):
        return self.user.email

    def generate_otp(self):
        """Generate a 6-digit OTP and save it."""
        self.otp = ''.join(random.choices(string.digits, k=6))
        self.otp_created_at = timezone.now()
        self.save()
        return self.otp

    def is_otp_valid(self, otp):
        """Check if OTP matches and is not expired."""
        if not self.otp or not self.otp_created_at:
            return False
        if self.otp != otp:
            return False
        expiry = self.otp_created_at + timedelta(seconds=settings.OTP_EXPIRY_SECONDS)
        return timezone.now() <= expiry


class Product(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, max_length=255)
    description = models.TextField()
    short_description = models.TextField(blank=True)
    specifications = models.JSONField(default=dict, blank=True)
    dimensions = models.CharField(max_length=100, blank=True)
    material = models.CharField(max_length=100, blank=True)
    weight = models.CharField(max_length=50, blank=True)
    price_inr = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price in Indian Rupees")
    price_usd = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price in US Dollars")
    sku = models.CharField(max_length=50, unique=True)
    category = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True, blank=True)
    collection = models.ForeignKey('Collection', on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)   # <-- NEW
    views_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    meta_title = models.CharField(max_length=200, blank=True)
    meta_description = models.TextField(blank=True)
    keywords = models.CharField(max_length=200, blank=True)

    translations = GenericRelation('Translation')

    @property
    def average_rating(self):
        reviews = self.reviews.filter(is_approved=True)
        if not reviews.exists():
            return 5.0
        from django.db.models import Avg
        val = reviews.aggregate(Avg('rating'))['rating__avg']
        return round(float(val), 1) if val else 5.0

    @property
    def review_count(self):
        return self.reviews.filter(is_approved=True).count()

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['-created_at']


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    translations = GenericRelation('Translation')

    def __str__(self):
        return self.name


class Collection(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    translations = GenericRelation('Translation')

    def __str__(self):
        return self.name


class Image(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    images = models.ImageField(upload_to='product_images/')
    alt_text = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order']


class Video(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='videos')
    videos = models.FileField(upload_to='product_videos/')
    title = models.CharField(max_length=200, blank=True)


class Translation(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    language_code = models.CharField(max_length=10, choices=settings.SUPPORTED_LANGUAGES)
    field_name = models.CharField(max_length=100)
    translated_text = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['content_type', 'object_id', 'language_code', 'field_name']]
        indexes = [
            models.Index(fields=['content_type', 'object_id', 'language_code']),
        ]

    def __str__(self):
        return f"{self.content_object} - {self.language_code} - {self.field_name}"


class CurrencyRate(models.Model):
    currency_code = models.CharField(max_length=3, unique=True)
    rate_to_usd = models.DecimalField(max_digits=10, decimal_places=4)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.currency_code}: {self.rate_to_usd}"


class Inquiry(models.Model):
    STATUS_CHOICES = [
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('quotation_sent', 'Quotation Sent'),
        ('negotiating', 'Negotiating'),
        ('confirmed', 'Confirmed'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    ]
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    customer_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField(default=1)
    requirements = models.TextField(blank=True)
    attachments = models.FileField(upload_to='inquiries/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    admin_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Inquiry from {self.customer_name} - {self.product}"


class InquiryReply(models.Model):
    inquiry = models.ForeignKey(Inquiry, on_delete=models.CASCADE, related_name='replies')
    message = models.TextField()
    sent_by_admin = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and self.sent_by_admin:
            from .email_utils import send_inquiry_reply_email
            send_inquiry_reply_email(self, self.inquiry)


# ---------- ORDER & 24-HOUR PAYMENT LINK MODELS ----------
class Order(models.Model):
    STATUS_CHOICES = [
        ('pending_payment', 'Pending Payment (24h Link Active)'),
        ('paid', 'Paid / Confirmed'),
        ('processing', 'In Crafting / Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('refund_requested', 'Cancellation & Refund Requested'),
        ('refunded', 'Refunded & Reversed'),
        ('expired', 'Expired (24h Cutoff Passed)'),
        ('cancelled', 'Cancelled'),
    ]

    order_number = models.CharField(max_length=64, unique=True, editable=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    customer_name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)

    # Shipping Address (Worldwide)
    country = models.CharField(max_length=100)
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=30)

    # Amounts & Currency
    currency = models.CharField(max_length=10, default='USD')
    subtotal_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    gateway_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    shipping_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    # Status & 24-Hour Expiration Token
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending_payment')
    payment_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    payment_link_expires_at = models.DateTimeField(null=True, blank=True)
    
    # Gateway Tracking
    payment_gateway = models.CharField(max_length=50, blank=True, default='')
    gateway_order_id = models.CharField(max_length=150, blank=True, default='')
    gateway_payment_id = models.CharField(max_length=150, blank=True, default='')

    # Cancellation & Refund Tracking
    cancellation_reason = models.TextField(blank=True, default='')
    cancellation_requested_at = models.DateTimeField(null=True, blank=True)
    refund_id = models.CharField(max_length=150, blank=True, default='')
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    refund_status = models.CharField(max_length=50, blank=True, default='')
    refunded_at = models.DateTimeField(null=True, blank=True)
    admin_refund_notes = models.TextField(blank=True, default='')

    # Shipping & Live Tracking
    courier_name = models.CharField(max_length=100, blank=True, default='')
    tracking_number = models.CharField(max_length=100, blank=True, default='')
    tracking_url = models.URLField(max_length=500, blank=True, default='')
    shipped_at = models.DateTimeField(null=True, blank=True)

    customer_notes = models.TextField(blank=True)
    admin_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Order #{self.order_number} - {self.customer_name} ({self.status})"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if is_new:
            if not self.order_number:
                # Generate human-friendly order reference: LBC-YYYYMMDD-XXXX
                date_str = timezone.now().strftime('%Y%m%d')
                random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
                self.order_number = f"LBC-{date_str}-{random_suffix}"
            if not self.payment_link_expires_at:
                # Default 24-hour expiration window
                self.payment_link_expires_at = timezone.now() + timedelta(hours=24)

        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        if self.status in ['paid', 'processing', 'shipped', 'delivered', 'cancelled']:
            return False
        if not self.payment_link_expires_at:
            return False
        return timezone.now() > self.payment_link_expires_at

    @property
    def seconds_remaining(self):
        if self.status in ['paid', 'processing', 'shipped', 'delivered', 'cancelled']:
            return 0
        if not self.payment_link_expires_at:
            return 0
        diff = (self.payment_link_expires_at - timezone.now()).total_seconds()
        return max(0, int(diff))

    @property
    def live_tracking_url(self):
        if self.tracking_url:
            return self.tracking_url
        if not self.tracking_number:
            return ''
        courier = (self.courier_name or '').lower().strip()
        tn = self.tracking_number.strip()
        if 'dhl' in courier:
            return f"https://www.dhl.com/en/express/tracking.html?AWB={tn}"
        elif 'fedex' in courier:
            return f"https://www.fedex.com/fedextrack/?trknbr={tn}"
        elif 'ups' in courier:
            return f"https://www.ups.com/track?tracknum={tn}"
        elif 'bluedart' in courier or 'blue dart' in courier:
            return f"https://www.bluedart.com/tracking?track={tn}"
        elif 'delhivery' in courier:
            return f"https://www.delhivery.com/track/package/{tn}"
        elif 'india post' in courier or 'speed post' in courier or 'indiapost' in courier:
            return f"https://www.indiapost.gov.in/_layouts/15/dpt.cept.tracking/trackconsignment.aspx"
        return f"https://www.google.com/search?q={urllib.parse.quote((self.courier_name + ' ' if self.courier_name else '') + tn + ' tracking')}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    product_title = models.CharField(max_length=255)
    sku = models.CharField(max_length=64, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    total_price = models.DecimalField(max_digits=12, decimal_places=2)
    image_url = models.CharField(max_length=500, blank=True)

    def __str__(self):
        return f"{self.product_title} x {self.quantity} (Order #{self.order.order_number})"


class SiteBanner(models.Model):
    """
    Homepage and site-wide luxury banner configuration.
    Allows admins to change hero background video, poster fallback,
    down / secondary showcase image, and promotional copy dynamically.
    """
    title = models.CharField(max_length=255, blank=True, default="Sacred Masterpieces Carved for Eternity")
    subtitle = models.TextField(
        blank=True,
        default="Museum-grade bone carvings and imperial artistry, ethically reclaimed and handcrafted by generational master sculptors."
    )
    tagline = models.CharField(max_length=150, blank=True, default="Heritage & Imperial Precision")

    # Hero Video (File upload or external URL fallback)
    video = models.FileField(upload_to='banners/videos/', blank=True, null=True)
    video_url = models.CharField(max_length=500, blank=True, default='')

    # Poster image for hero video loading / fallback
    poster_image = models.ImageField(upload_to='banners/images/', blank=True, null=True)

    # Down / secondary showcase banner image (e.g., underneath hero or heritage section)
    down_image = models.ImageField(upload_to='banners/images/', blank=True, null=True)

    # CTA Action
    button_text = models.CharField(max_length=100, blank=True, default="Explore Imperial Collection")
    button_link = models.CharField(max_length=255, blank=True, default="/products/")

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"Banner #{self.pk}: {self.title[:40]} (Active: {self.is_active})"


class Review(models.Model):
    """
    Verified Collector Reviews & Testimonials.
    Restricted to patrons who have ordered and acquired the masterpiece.
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviews')
    customer_name = models.CharField(max_length=150)
    customer_email = models.EmailField()
    customer_country = models.CharField(max_length=100, blank=True, default='')
    rating = models.PositiveSmallIntegerField(default=5)  # 1 to 5
    title = models.CharField(max_length=200, blank=True, default='')
    comment = models.TextField()
    is_verified_purchase = models.BooleanField(default=True)
    is_approved = models.BooleanField(default=True)
    is_featured_home = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.rating}★ by {self.customer_name} on {self.product.title}"

