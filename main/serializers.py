from rest_framework import serializers
from .models import (
    UserProfile, Product, Category, Collection, Image, Video,
    CurrencyRate, Translation, Inquiry, Order, OrderItem, SiteBanner, Review
)
from django.contrib.auth.models import User
from django.conf import settings
from decimal import Decimal



class ImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = Image
        fields = ['id', 'images', 'url', 'alt_text', 'sort_order']

    def get_url(self, obj):
        if obj.images:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.images.url)
            return obj.images.url
        return ''


class VideoSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = Video
        fields = ['id', 'videos', 'url', 'title']

    def get_url(self, obj):
        if obj.videos:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.videos.url)
            return obj.videos.url
        return ''


class TranslationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Translation
        fields = ['language_code', 'field_name', 'translated_text']


class LocalizedModelSerializer(serializers.ModelSerializer):
    """
    Helper base serializer that overlays existing fields with 
    their translated values. If not yet translated in DB, automatically
    translates on the fly and caches to the Translation table.
    """
    def to_representation(self, instance):
        data = super().to_representation(instance)
        lang = self.context.get('language', 'en')

        if lang and lang != 'en':
            # Retrieve cached translations
            translations = {
                t.field_name: t.translated_text
                for t in instance.translations.filter(language_code=lang)
            }
            fields_to_check = ['title', 'name', 'description', 'short_description', 'material', 'dimensions']
            for field in fields_to_check:
                if field in data and data[field]:
                    cached = translations.get(field)
                    if cached and cached.strip().lower() != str(data[field]).strip().lower():
                        data[field] = cached
                    else:
                        # Auto-translate on the fly and cache into DB
                        try:
                            from .translation_utils import translate_text, save_translation
                            translated = translate_text(data[field], lang, source_lang='en')
                            if translated and translated.strip().lower() != str(data[field]).strip().lower():
                                save_translation(instance, field, lang, translated)
                                data[field] = translated
                        except Exception as e:
                            pass
        return data


class CategorySerializer(LocalizedModelSerializer):
    translations = TranslationSerializer(many=True, read_only=True)

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'parent', 'is_active', 'translations']


class CollectionSerializer(LocalizedModelSerializer):
    translations = TranslationSerializer(many=True, read_only=True)

    class Meta:
        model = Collection
        fields = ['id', 'name', 'slug', 'description', 'is_active', 'translations']


class ProductSerializer(LocalizedModelSerializer):
    images = ImageSerializer(many=True, read_only=True)
    videos = VideoSerializer(many=True, read_only=True)
    category = CategorySerializer(read_only=True)
    collection = CollectionSerializer(read_only=True)
    translations = TranslationSerializer(many=True, read_only=True)
    average_rating = serializers.FloatField(read_only=True)
    review_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'title', 'slug', 'description', 'short_description',
            'specifications', 'dimensions', 'material', 'weight',
            'price_inr', 'price_usd', 'sku', 'category', 'collection',
            'is_active', 'views_count', 'average_rating', 'review_count',
            'created_at', 'updated_at',
            'meta_title', 'meta_description', 'keywords',
            'images', 'videos', 'translations'
        ]


class ReviewSerializer(serializers.ModelSerializer):
    product_title = serializers.CharField(source='product.title', read_only=True)
    product_slug = serializers.CharField(source='product.slug', read_only=True)

    class Meta:
        model = Review
        fields = [
            'id', 'product', 'product_title', 'product_slug', 'order',
            'customer_name', 'customer_email', 'customer_country',
            'rating', 'title', 'comment', 'is_verified_purchase',
            'is_approved', 'is_featured_home', 'created_at'
        ]
        read_only_fields = ['id', 'is_verified_purchase', 'is_approved', 'created_at']


class CurrencyRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CurrencyRate
        fields = ['currency_code', 'rate_to_usd', 'updated_at']


class InquirySerializer(serializers.ModelSerializer):
    class Meta:
        model = Inquiry
        fields = '__all__'
        read_only_fields = ['id', 'status', 'created_at', 'updated_at', 'admin_notes']
        
        

class UserRegistrationSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(write_only=True, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'password', 'first_name', 'last_name', 'phone')
        extra_kwargs = {
            'username': {'required': False},
            'email': {'required': True},
        }

    def validate(self, data):
        if not data.get('email'):
            raise serializers.ValidationError({'email': 'Email is required.'})
        data['username'] = data['email']   # username = email
        return data

    def create(self, validated_data):
        phone = validated_data.pop('phone', '')
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', '')
        )
        # Signal will create profile and send OTP, but we also need to set phone
        profile = user.profile
        profile.phone = phone
        profile.save()
        return user

class OTPVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ('phone', 'is_email_verified')


# ---------- ORDER SERIALIZERS ----------
class OrderItemSerializer(serializers.ModelSerializer):
    product_slug = serializers.CharField(source='product.slug', read_only=True)

    class Meta:
        model = OrderItem
        fields = ['id', 'product', 'product_slug', 'product_title', 'sku', 'unit_price', 'quantity', 'total_price', 'image_url']


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    seconds_remaining = serializers.IntegerField(read_only=True)
    payment_url = serializers.SerializerMethodField()
    live_tracking_url = serializers.CharField(read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'customer_name', 'email', 'phone',
            'country', 'address_line1', 'address_line2', 'city', 'state', 'postal_code',
            'currency', 'subtotal_amount', 'gateway_fee', 'shipping_amount', 'total_amount',
            'status', 'payment_token', 'payment_link_expires_at',
            'payment_gateway', 'gateway_order_id', 'gateway_payment_id',
            'cancellation_reason', 'cancellation_requested_at',
            'refund_id', 'refund_amount', 'refund_status', 'refunded_at', 'admin_refund_notes',
            'courier_name', 'tracking_number', 'tracking_url', 'shipped_at', 'live_tracking_url',
            'is_expired', 'seconds_remaining', 'payment_url',
            'customer_notes', 'items', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'order_number', 'payment_token', 'payment_link_expires_at',
            'status', 'is_expired', 'seconds_remaining', 'payment_url', 'live_tracking_url',
            'refund_id', 'refund_amount', 'refund_status', 'refunded_at',
            'created_at', 'updated_at'
        ]

    def get_payment_url(self, obj):
        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000').rstrip('/')
        return f"{frontend_url}/pay/{obj.payment_token}"


class CreateOrderItemInputSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(required=False, allow_null=True)
    title = serializers.CharField(max_length=255)
    sku = serializers.CharField(max_length=64, required=False, allow_blank=True)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    quantity = serializers.IntegerField(min_value=1)
    image_url = serializers.CharField(max_length=500, required=False, allow_blank=True)


class CreateOrderSerializer(serializers.Serializer):
    customer_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    
    country = serializers.CharField(max_length=100)
    address_line1 = serializers.CharField(max_length=255)
    address_line2 = serializers.CharField(max_length=255, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100)
    state = serializers.CharField(max_length=100, required=False, allow_blank=True)
    postal_code = serializers.CharField(max_length=30)
    
    currency = serializers.CharField(max_length=10, default='USD')
    shipping_amount = serializers.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    customer_notes = serializers.CharField(required=False, allow_blank=True)
    items = CreateOrderItemInputSerializer(many=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one item is required in the order.")
        return value

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        user = self.context.get('user')
        if user and not user.is_authenticated:
            user = None

        shipping_amount = validated_data.get('shipping_amount', Decimal('0.00'))

        # Calculate subtotal and gateway convenience fee
        subtotal_amount = sum(Decimal(str(item['unit_price'])) * item['quantity'] for item in items_data)
        fee_percent = Decimal(str(getattr(settings, 'GATEWAY_FEE_PERCENT', 2.0)))
        gateway_fee = (subtotal_amount * fee_percent / Decimal('100')).quantize(Decimal('0.01')) if fee_percent > 0 else Decimal('0.00')
        total_amount = subtotal_amount + Decimal(str(shipping_amount)) + gateway_fee

        order = Order.objects.create(
            user=user,
            subtotal_amount=subtotal_amount,
            gateway_fee=gateway_fee,
            total_amount=total_amount,
            **validated_data
        )

        for item_data in items_data:
            product = None
            product_id = item_data.get('product_id')
            if product_id:
                product = Product.objects.filter(id=product_id).first()

            unit_price = Decimal(str(item_data['unit_price']))
            qty = item_data['quantity']
            total_price = unit_price * qty

            OrderItem.objects.create(
                order=order,
                product=product,
                product_title=item_data['title'],
                sku=item_data.get('sku', ''),
                unit_price=unit_price,
                quantity=qty,
                total_price=total_price,
                image_url=item_data.get('image_url', '')
            )

        # Generate payment link and send luxury 24-hour email
        payment_url = f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:3000').rstrip('/')}/pay/{order.payment_token}"
        from .email_utils import send_order_payment_link_email
        send_order_payment_link_email(order, payment_url)

        return order


class EmailOTPRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class EmailOTPVerifyLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)


class SiteBannerSerializer(serializers.ModelSerializer):
    video_file_url = serializers.SerializerMethodField()
    poster_image_url = serializers.SerializerMethodField()
    down_image_url = serializers.SerializerMethodField()

    class Meta:
        model = SiteBanner
        fields = [
            'id', 'title', 'subtitle', 'tagline',
            'video', 'video_url', 'video_file_url',
            'poster_image', 'poster_image_url',
            'down_image', 'down_image_url',
            'button_text', 'button_link',
            'is_active', 'created_at', 'updated_at'
        ]

    def get_video_file_url(self, obj):
        if obj.video:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.video.url)
            return obj.video.url
        return obj.video_url or ''

    def get_poster_image_url(self, obj):
        if obj.poster_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.poster_image.url)
            return obj.poster_image.url
        return ''

    def get_down_image_url(self, obj):
        if obj.down_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.down_image.url)
            return obj.down_image.url
        return ''
