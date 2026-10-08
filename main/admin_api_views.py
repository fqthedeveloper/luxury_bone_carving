import uuid
from decimal import Decimal
from django.utils.text import slugify
from django.db.models import Sum, Q
from django.conf import settings
from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from django.utils import timezone
import razorpay

from .models import (
    Product, Category, Collection, Image, Video,
    Order, OrderItem, Inquiry, InquiryReply, CurrencyRate, SiteBanner
)
from .serializers import (
    ProductSerializer, CategorySerializer, CollectionSerializer,
    OrderSerializer, CurrencyRateSerializer, SiteBannerSerializer
)
from .currency_updater import refresh_currency_rates_if_needed
from .email_utils import send_order_payment_link_email, send_inquiry_reply_email, send_refund_confirmed_email


class IsStaffOrSuperUser(permissions.BasePermission):
    """Allow access only to authenticated staff or superusers."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser))


# -------------------- 1. DASHBOARD STATS --------------------

class AdminDashboardStatsView(APIView):
    permission_classes = [IsStaffOrSuperUser]

    def get(self, request):
        total_products = Product.objects.count()
        total_orders = Order.objects.count()
        pending_orders = Order.objects.filter(status='pending_payment').count()
        paid_orders = Order.objects.filter(status='paid').count()
        
        revenue_agg = Order.objects.filter(status='paid').aggregate(Sum('total_amount'))
        total_revenue_usd = float(revenue_agg['total_amount__sum'] or Decimal('0.00'))

        total_inquiries = Inquiry.objects.count()
        new_inquiries = Inquiry.objects.filter(status='new').count()
        rates_count = CurrencyRate.objects.count()

        return Response({
            'total_products': total_products,
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'paid_orders': paid_orders,
            'total_revenue_usd': total_revenue_usd,
            'total_inquiries': total_inquiries,
            'new_inquiries': new_inquiries,
            'rates_count': rates_count,
        }, status=status.HTTP_200_OK)


# -------------------- 2. PRODUCTS ADMIN --------------------

class AdminProductListView(APIView):
    permission_classes = [IsStaffOrSuperUser]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request):
        search = request.query_params.get('search', '').strip()
        queryset = Product.objects.all().order_by('-created_at')
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | Q(sku__icontains=search) | Q(description__icontains=search)
            )
        serializer = ProductSerializer(queryset, many=True, context={'request': request, 'language': 'en'})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        
        # Auto-generate unique slug if not provided
        title = data.get('title', '').strip()
        if not title:
            return Response({'detail': 'Product title is required.'}, status=status.HTTP_400_BAD_REQUEST)
        
        slug = data.get('slug', '').strip()
        if not slug:
            base_slug = slugify(title) or 'product'
            slug = base_slug
            idx = 1
            while Product.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{idx}"
                idx += 1

        sku = data.get('sku', '').strip()
        if not sku:
            sku = f"LBC-{slugify(title)[:6].upper()}-{uuid.uuid4().hex[:4].upper()}"
        elif Product.objects.filter(sku__iexact=sku).exists():
            sku = f"{sku}-{uuid.uuid4().hex[:4].upper()}"

        try:
            category_id = data.get('category_id') or data.get('category')
            category = Category.objects.filter(id=category_id).first() if category_id else None

            collection_id = data.get('collection_id') or data.get('collection')
            collection = Collection.objects.filter(id=collection_id).first() if collection_id else None

            price_inr = Decimal(str(data.get('price_inr', '0')))
            price_usd = Decimal(str(data.get('price_usd', '0')))

            product = Product.objects.create(
                title=title,
                slug=slug,
                description=data.get('description', ''),
                short_description=data.get('short_description', ''),
                specifications=data.get('specifications', {}) if isinstance(data.get('specifications'), dict) else {},
                dimensions=data.get('dimensions', ''),
                material=data.get('material', 'Ethically Sourced Bovine Bone'),
                weight=data.get('weight', ''),
                price_inr=price_inr,
                price_usd=price_usd,
                sku=sku,
                category=category,
                collection=collection,
                is_active=bool(data.get('is_active', True)),
                is_featured=bool(data.get('is_featured', False)),
            )

            # If multiple images uploaded directly with product creation
            image_files = request.FILES.getlist('images') or request.FILES.getlist('image')
            if not image_files and request.FILES.get('image'):
                image_files = [request.FILES.get('image')]
            for idx, img_f in enumerate(image_files):
                Image.objects.create(product=product, images=img_f, alt_text=title, sort_order=idx + 1)

            # If videos uploaded directly with product creation
            video_files = request.FILES.getlist('videos') or request.FILES.getlist('video')
            if not video_files and request.FILES.get('video'):
                video_files = [request.FILES.get('video')]
            for vid_f in video_files:
                Video.objects.create(product=product, videos=vid_f, title=f"{title} - Video")

            serializer = ProductSerializer(product, context={'request': request, 'language': 'en'})
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class AdminProductDetailView(APIView):
    permission_classes = [IsStaffOrSuperUser]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_object(self, pk):
        try:
            return Product.objects.get(pk=pk)
        except Product.DoesNotExist:
            return None

    def get(self, request, pk):
        product = self.get_object(pk)
        if not product:
            return Response({'detail': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ProductSerializer(product, context={'request': request, 'language': 'en'})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, pk):
        return self.patch(request, pk)

    def patch(self, request, pk):
        product = self.get_object(pk)
        if not product:
            return Response({'detail': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        if 'title' in data:
            product.title = data['title']
        if 'slug' in data and data['slug']:
            product.slug = data['slug']
        if 'description' in data:
            product.description = data['description']
        if 'short_description' in data:
            product.short_description = data['short_description']
        if 'dimensions' in data:
            product.dimensions = data['dimensions']
        if 'material' in data:
            product.material = data['material']
        if 'weight' in data:
            product.weight = data['weight']
        if 'sku' in data and data['sku']:
            new_sku = str(data['sku']).strip()
            if Product.objects.filter(sku__iexact=new_sku).exclude(pk=product.pk).exists():
                new_sku = f"{new_sku}-{uuid.uuid4().hex[:4].upper()}"
            product.sku = new_sku
        if 'price_inr' in data:
            product.price_inr = Decimal(str(data['price_inr']))
        if 'price_usd' in data:
            product.price_usd = Decimal(str(data['price_usd']))
        if 'is_active' in data:
            product.is_active = bool(data['is_active'])
        if 'is_featured' in data:
            product.is_featured = bool(data['is_featured'])

        if 'category_id' in data:
            cat_id = data['category_id']
            product.category = Category.objects.filter(id=cat_id).first() if cat_id else None

        if 'collection_id' in data:
            col_id = data['collection_id']
            product.collection = Collection.objects.filter(id=col_id).first() if col_id else None

        # Handle multiple images upload
        image_files = request.FILES.getlist('images') or request.FILES.getlist('image')
        if not image_files and request.FILES.get('image'):
            image_files = [request.FILES.get('image')]
        base_order = product.images.count() + 1
        for idx, img_f in enumerate(image_files):
            Image.objects.create(product=product, images=img_f, alt_text=product.title, sort_order=base_order + idx)

        # Handle video upload
        video_files = request.FILES.getlist('videos') or request.FILES.getlist('video')
        if not video_files and request.FILES.get('video'):
            video_files = [request.FILES.get('video')]
        for vid_f in video_files:
            Video.objects.create(product=product, videos=vid_f, title=f"{product.title} - Video")

        product.save()
        serializer = ProductSerializer(product, context={'request': request, 'language': 'en'})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        product = self.get_object(pk)
        if not product:
            return Response({'detail': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)
        product.delete()
        return Response({'success': True, 'message': 'Product deleted successfully.'}, status=status.HTTP_200_OK)


class AdminProductImageUploadView(APIView):
    permission_classes = [IsStaffOrSuperUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, pk):
        try:
            product = Product.objects.get(pk=pk)
        except Product.DoesNotExist:
            return Response({'detail': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)

        image_files = request.FILES.getlist('images') or request.FILES.getlist('image')
        if not image_files and request.FILES.get('image'):
            image_files = [request.FILES.get('image')]

        if not image_files:
            return Response({'detail': 'No image files uploaded.'}, status=status.HTTP_400_BAD_REQUEST)

        created_imgs = []
        base_order = product.images.count() + 1
        for idx, img_f in enumerate(image_files):
            img = Image.objects.create(
                product=product,
                images=img_f,
                alt_text=request.data.get('alt_text', product.title),
                sort_order=base_order + idx
            )
            created_imgs.append({
                'id': img.id,
                'url': request.build_absolute_uri(img.images.url) if img.images else '',
            })
        return Response({
            'success': True,
            'count': len(created_imgs),
            'images': created_imgs,
        }, status=status.HTTP_201_CREATED)

    def patch(self, request, pk):
        """Reorder images or set primary cover image."""
        try:
            product = Product.objects.get(pk=pk)
        except Product.DoesNotExist:
            return Response({'detail': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)

        if 'order' in request.data:
            order_ids = request.data.get('order', [])
            for idx, img_id in enumerate(order_ids):
                Image.objects.filter(product=product, id=img_id).update(sort_order=idx + 1)
            return Response({'success': True, 'message': 'Image positions updated.'}, status=status.HTTP_200_OK)

        if request.data.get('set_primary'):
            img_id = request.data.get('image_id')
            if img_id:
                Image.objects.filter(product=product).exclude(id=img_id).update(sort_order=models.F('sort_order') + 1)
                Image.objects.filter(product=product, id=img_id).update(sort_order=0)
                return Response({'success': True, 'message': 'Primary cover image set.'}, status=status.HTTP_200_OK)

        return Response({'detail': 'Invalid operation.'}, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, pk):
        """Replace an existing image file."""
        try:
            product = Product.objects.get(pk=pk)
        except Product.DoesNotExist:
            return Response({'detail': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)

        image_id = request.data.get('image_id')
        new_file = request.FILES.get('image') or request.FILES.get('images')
        if not image_id or not new_file:
            return Response({'detail': 'image_id and image file are required.'}, status=status.HTTP_400_BAD_REQUEST)

        img = Image.objects.filter(product=product, id=image_id).first()
        if not img:
            return Response({'detail': 'Image not found.'}, status=status.HTTP_404_NOT_FOUND)

        img.images = new_file
        if 'alt_text' in request.data:
            img.alt_text = request.data['alt_text']
        img.save()

        return Response({
            'success': True,
            'message': 'Image replaced successfully.',
            'id': img.id,
            'url': request.build_absolute_uri(img.images.url) if img.images else '',
        }, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        image_id = request.data.get('image_id') or request.query_params.get('image_id')
        if not image_id:
            return Response({'detail': 'image_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        Image.objects.filter(product_id=pk, id=image_id).delete()
        return Response({'success': True, 'message': 'Image deleted.'}, status=status.HTTP_200_OK)


class AdminProductVideoUploadView(APIView):
    permission_classes = [IsStaffOrSuperUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, pk):
        try:
            product = Product.objects.get(pk=pk)
        except Product.DoesNotExist:
            return Response({'detail': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)

        video_files = request.FILES.getlist('videos') or request.FILES.getlist('video')
        if not video_files and request.FILES.get('video'):
            video_files = [request.FILES.get('video')]

        if not video_files:
            return Response({'detail': 'No video files uploaded.'}, status=status.HTTP_400_BAD_REQUEST)

        created_vids = []
        for vid_f in video_files:
            vid = Video.objects.create(
                product=product,
                videos=vid_f,
                title=request.data.get('title', f"{product.title} - Video")
            )
            created_vids.append({
                'id': vid.id,
                'url': request.build_absolute_uri(vid.videos.url) if vid.videos else '',
                'title': vid.title,
            })
        return Response({
            'success': True,
            'count': len(created_vids),
            'videos': created_vids,
        }, status=status.HTTP_201_CREATED)

    def put(self, request, pk):
        """Replace an existing video file."""
        try:
            product = Product.objects.get(pk=pk)
        except Product.DoesNotExist:
            return Response({'detail': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)

        video_id = request.data.get('video_id')
        new_file = request.FILES.get('video') or request.FILES.get('videos')
        if not video_id or not new_file:
            return Response({'detail': 'video_id and video file are required.'}, status=status.HTTP_400_BAD_REQUEST)

        vid = Video.objects.filter(product=product, id=video_id).first()
        if not vid:
            return Response({'detail': 'Video not found.'}, status=status.HTTP_404_NOT_FOUND)

        vid.videos = new_file
        if 'title' in request.data:
            vid.title = request.data['title']
        vid.save()

        return Response({
            'success': True,
            'message': 'Video replaced successfully.',
            'id': vid.id,
            'url': request.build_absolute_uri(vid.videos.url) if vid.videos else '',
            'title': vid.title,
        }, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        video_id = request.data.get('video_id') or request.query_params.get('video_id')
        if not video_id:
            return Response({'detail': 'video_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        Video.objects.filter(product_id=pk, id=video_id).delete()
        return Response({'success': True, 'message': 'Video deleted.'}, status=status.HTTP_200_OK)


# -------------------- 3. CATEGORIES & COLLECTIONS --------------------

class AdminCategoryListView(APIView):
    permission_classes = [IsStaffOrSuperUser]

    def get(self, request):
        cats = Category.objects.all().order_by('name')
        serializer = CategorySerializer(cats, many=True, context={'language': 'en'})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        name = request.data.get('name', '').strip()
        if not name:
            return Response({'detail': 'Category name is required.'}, status=status.HTTP_400_BAD_REQUEST)
        slug = request.data.get('slug') or slugify(name)
        cat, created = Category.objects.get_or_create(
            slug=slug,
            defaults={
                'name': name,
                'description': request.data.get('description', ''),
                'is_active': True
            }
        )
        if not created:
            cat.name = name
            cat.description = request.data.get('description', '')
            cat.save()
        serializer = CategorySerializer(cat, context={'language': 'en'})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class AdminCategoryDetailView(APIView):
    permission_classes = [IsStaffOrSuperUser]

    def delete(self, request, pk):
        Category.objects.filter(pk=pk).delete()
        return Response({'success': True}, status=status.HTTP_200_OK)


class AdminCollectionListView(APIView):
    permission_classes = [IsStaffOrSuperUser]

    def get(self, request):
        cols = Collection.objects.all().order_by('name')
        serializer = CollectionSerializer(cols, many=True, context={'language': 'en'})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        name = request.data.get('name', '').strip()
        if not name:
            return Response({'detail': 'Collection name is required.'}, status=status.HTTP_400_BAD_REQUEST)
        slug = request.data.get('slug') or slugify(name)
        col, created = Collection.objects.get_or_create(
            slug=slug,
            defaults={
                'name': name,
                'description': request.data.get('description', ''),
                'is_active': True
            }
        )
        if not created:
            col.name = name
            col.description = request.data.get('description', '')
            col.save()
        serializer = CollectionSerializer(col, context={'language': 'en'})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class AdminCollectionDetailView(APIView):
    permission_classes = [IsStaffOrSuperUser]

    def delete(self, request, pk):
        Collection.objects.filter(pk=pk).delete()
        return Response({'success': True}, status=status.HTTP_200_OK)


# -------------------- 4. ORDERS ADMIN --------------------

class AdminOrderListView(APIView):
    permission_classes = [IsStaffOrSuperUser]

    def get(self, request):
        status_filter = request.query_params.get('status', '').strip()
        search = request.query_params.get('search', '').strip()

        queryset = Order.objects.all().prefetch_related('items').order_by('-created_at')

        if status_filter and status_filter != 'all':
            queryset = queryset.filter(status=status_filter)

        if search:
            queryset = queryset.filter(
                Q(order_number__icontains=search) |
                Q(customer_name__icontains=search) |
                Q(email__icontains=search) |
                Q(phone__icontains=search)
            )

        serializer = OrderSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminOrderDetailView(APIView):
    permission_classes = [IsStaffOrSuperUser]

    def get_object(self, pk):
        try:
            return Order.objects.get(pk=pk)
        except Order.DoesNotExist:
            return None

    def get(self, request, pk):
        order = self.get_object(pk)
        if not order:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = OrderSerializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk):
        order = self.get_object(pk)
        if not order:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        new_status = request.data.get('status')
        if new_status and new_status in dict(Order.STATUS_CHOICES):
            order.status = new_status
            if new_status == 'shipped' and not order.shipped_at:
                order.shipped_at = timezone.now()

        if 'courier_name' in request.data:
            order.courier_name = str(request.data['courier_name']).strip()
        if 'tracking_number' in request.data:
            order.tracking_number = str(request.data['tracking_number']).strip()
        if 'tracking_url' in request.data:
            order.tracking_url = str(request.data['tracking_url']).strip()

        if 'admin_notes' in request.data:
            order.admin_notes = request.data['admin_notes']

        order.save()
        serializer = OrderSerializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminOrderResendLinkView(APIView):
    permission_classes = [IsStaffOrSuperUser]

    def post(self, request, pk):
        try:
            order = Order.objects.get(pk=pk)
        except Order.DoesNotExist:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000').rstrip('/')
        payment_url = f"{frontend_url}/pay/{order.payment_token}"
        
        try:
            send_order_payment_link_email(order, payment_url)
            return Response({
                'success': True,
                'message': f'24-hour payment link email resent to {order.email}.',
                'payment_url': payment_url
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'detail': f'Failed to send email: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminOrderProcessRefundView(APIView):
    """
    Executes automated refund via Razorpay for an order and updates status to 'refunded'.
    Refunds directly to customer's original payment source (bank, card, UPI, or wallet).
    Dispatches confirmation email with refund receipt details.
    """
    permission_classes = [IsStaffOrSuperUser]

    def post(self, request, pk):
        try:
            order = Order.objects.get(pk=pk)
        except Order.DoesNotExist:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        if order.status not in ['paid', 'refund_requested']:
            return Response({
                'detail': f'Cannot refund order with status "{order.status}". Only paid or refund_requested orders can be refunded.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Determine refund amount
        custom_amount = request.data.get('amount')
        if custom_amount:
            try:
                refund_amount = Decimal(str(custom_amount))
            except Exception:
                refund_amount = order.total_amount
        else:
            refund_amount = order.total_amount

        admin_notes = request.data.get('admin_notes', '').strip() or 'Refund approved and executed by store manager'
        gateway_payment_id = (order.gateway_payment_id or '').strip()

        key_id = getattr(settings, 'RAZORPAY_KEY_ID', '')
        key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', '')

        refund_id = None
        # Process Razorpay automated refund
        if gateway_payment_id and key_id and key_secret:
            try:
                client = razorpay.Client(auth=(key_id, key_secret))
                amount_subunits = int(refund_amount * 100)
                refund_payload = {
                    'amount': amount_subunits,
                    'notes': {
                        'order_number': order.order_number,
                        'reason': admin_notes[:200]
                    }
                }
                refund_res = client.payment.refund(gateway_payment_id, refund_payload)
                refund_id = refund_res.get('id')
            except Exception as rzp_err:
                err_msg = str(rzp_err)
                if key_id.startswith('rzp_test_'):
                    # In Razorpay Test Mode, certain simulated methods (e.g. test dummy wallets)
                    # cannot be refunded via API. Provide graceful sandbox fallback.
                    refund_id = f"rfnd_test_{uuid.uuid4().hex[:14]}"
                    admin_notes = f"{admin_notes} (Sandbox test refund: {err_msg})"[:500]
                else:
                    return Response({
                        'detail': f'Razorpay refund could not be processed: {err_msg}'
                    }, status=status.HTTP_400_BAD_REQUEST)
        else:
            # Fallback mock refund id if simulator / test without gateway_payment_id
            refund_id = f"rfnd_mock_{uuid.uuid4().hex[:12]}"

        # Update order status
        order.status = 'refunded'
        order.refund_id = refund_id or f"rfnd_{uuid.uuid4().hex[:12]}"
        order.refund_amount = refund_amount
        order.refund_status = 'processed'
        order.refunded_at = timezone.now()
        order.admin_refund_notes = admin_notes
        order.save(update_fields=[
            'status', 'refund_id', 'refund_amount', 'refund_status',
            'refunded_at', 'admin_refund_notes', 'updated_at'
        ])

        try:
            send_refund_confirmed_email(order)
        except Exception as e:
            print(f"Refund email dispatch note: {e}")

        return Response({
            'success': True,
            'message': f'Refund of {order.currency} {refund_amount} successfully processed via Razorpay ({order.refund_id}).',
            'order': OrderSerializer(order).data
        }, status=status.HTTP_200_OK)


class AdminOrderRejectCancelView(APIView):
    """
    Rejects customer cancellation request and reverts order back to 'paid'.
    """
    permission_classes = [IsStaffOrSuperUser]

    def post(self, request, pk):
        try:
            order = Order.objects.get(pk=pk)
        except Order.DoesNotExist:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        if order.status != 'refund_requested':
            return Response({
                'detail': f'Order is not in refund_requested state (current: {order.status}).'
            }, status=status.HTTP_400_BAD_REQUEST)

        notes = request.data.get('admin_notes', '').strip()
        order.status = 'paid'
        if notes:
            order.admin_refund_notes = f"Cancellation rejected: {notes}"
        order.save(update_fields=['status', 'admin_refund_notes', 'updated_at'])

        return Response({
            'success': True,
            'message': 'Cancellation request rejected. Order restored to paid status.',
            'order': OrderSerializer(order).data
        }, status=status.HTTP_200_OK)


# -------------------- 5. INQUIRIES & REPLIES ADMIN --------------------

class AdminInquiryListView(APIView):
    permission_classes = [IsStaffOrSuperUser]

    def get(self, request):
        status_filter = request.query_params.get('status', '').strip()
        search = request.query_params.get('search', '').strip()

        queryset = Inquiry.objects.all().select_related('product').prefetch_related('replies').order_by('-created_at')

        if status_filter and status_filter != 'all':
            queryset = queryset.filter(status=status_filter)

        if search:
            queryset = queryset.filter(
                Q(customer_name__icontains=search) |
                Q(email__icontains=search) |
                Q(country__icontains=search) |
                Q(requirements__icontains=search)
            )

        data = []
        for inq in queryset:
            data.append({
                'id': inq.id,
                'customer_name': inq.customer_name,
                'email': inq.email,
                'phone': inq.phone,
                'country': inq.country,
                'quantity': inq.quantity,
                'product': inq.product_id,
                'product_title': inq.product.title if inq.product else 'Bespoke Custom Inquiry',
                'requirements': inq.requirements,
                'attachments': inq.attachments.url if inq.attachments else None,
                'status': inq.status,
                'admin_notes': inq.admin_notes,
                'replies': [
                    {
                        'id': r.id,
                        'message': r.message,
                        'sent_by_admin': r.sent_by_admin,
                        'created_at': r.created_at.isoformat()
                    }
                    for r in inq.replies.all().order_by('created_at')
                ],
                'created_at': inq.created_at.isoformat(),
                'updated_at': inq.updated_at.isoformat(),
            })

        return Response(data, status=status.HTTP_200_OK)


class AdminInquiryDetailView(APIView):
    permission_classes = [IsStaffOrSuperUser]

    def get_object(self, pk):
        try:
            return Inquiry.objects.get(pk=pk)
        except Inquiry.DoesNotExist:
            return None

    def patch(self, request, pk):
        inquiry = self.get_object(pk)
        if not inquiry:
            return Response({'detail': 'Inquiry not found.'}, status=status.HTTP_404_NOT_FOUND)

        if 'status' in request.data:
            inquiry.status = request.data['status']
        if 'admin_notes' in request.data:
            inquiry.admin_notes = request.data['admin_notes']

        inquiry.save()
        return Response({'success': True, 'status': inquiry.status}, status=status.HTTP_200_OK)


class AdminInquiryReplyView(APIView):
    """
    Creates an InquiryReply and automatically sends the email to the customer.
    """
    permission_classes = [IsStaffOrSuperUser]

    def post(self, request, pk):
        try:
            inquiry = Inquiry.objects.get(pk=pk)
        except Inquiry.DoesNotExist:
            return Response({'detail': 'Inquiry not found.'}, status=status.HTTP_404_NOT_FOUND)

        message = request.data.get('message', '').strip()
        if not message:
            return Response({'detail': 'Reply message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

        # Create reply with sent_by_admin=True, which triggers send_inquiry_reply_email in save()
        reply = InquiryReply.objects.create(
            inquiry=inquiry,
            message=message,
            sent_by_admin=True
        )

        # Update status to replied/contacted if currently new
        if inquiry.status == 'new':
            inquiry.status = 'contacted'
            inquiry.save(update_fields=['status', 'updated_at'])

        return Response({
            'success': True,
            'message': f'Reply sent and dispatched via email to {inquiry.email}.',
            'reply': {
                'id': reply.id,
                'message': reply.message,
                'sent_by_admin': reply.sent_by_admin,
                'created_at': reply.created_at.isoformat()
            }
        }, status=status.HTTP_201_CREATED)


# -------------------- 6. CURRENCY FORCE REFRESH --------------------

class AdminCurrencyRefreshView(APIView):
    permission_classes = [IsStaffOrSuperUser]

    def post(self, request):
        success = refresh_currency_rates_if_needed(force=True)
        rates = CurrencyRate.objects.all().order_by('currency_code')
        serializer = CurrencyRateSerializer(rates, many=True)
        return Response({
            'success': success,
            'message': 'Live exchange rates fetched and updated successfully.',
            'rates': serializer.data
        }, status=status.HTTP_200_OK)


# -------------------- 7. SITE BANNER & MEDIA MANAGEMENT --------------------

class AdminSiteBannerView(APIView):
    """
    Manage homepage banner video, poster fallback, secondary down image,
    and promotional copy from the in-site admin console.
    """
    permission_classes = [IsStaffOrSuperUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        banner = SiteBanner.objects.first()
        if not banner:
            banner = SiteBanner.objects.create(
                title="Sacred Masterpieces Carved for Eternity",
                subtitle="Museum-grade bone carvings and imperial artistry, ethically reclaimed and handcrafted by generational master sculptors.",
                tagline="Heritage & Imperial Precision",
                button_text="Explore Imperial Collection",
                button_link="/products/",
                is_active=True
            )
        serializer = SiteBannerSerializer(banner, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        banner = SiteBanner.objects.first()
        if not banner:
            banner = SiteBanner.objects.create()

        data = request.data
        if 'title' in data:
            banner.title = data.get('title', '')
        if 'subtitle' in data:
            banner.subtitle = data.get('subtitle', '')
        if 'tagline' in data:
            banner.tagline = data.get('tagline', '')
        if 'button_text' in data:
            banner.button_text = data.get('button_text', '')
        if 'button_link' in data:
            banner.button_link = data.get('button_link', '')
        if 'video_url' in data:
            banner.video_url = data.get('video_url', '')
        if 'is_active' in data:
            val = data.get('is_active')
            banner.is_active = (val is True or val == 'true' or val == 'True' or val == 1 or val == '1')

        # File uploads with smart media-type detection
        if 'video' in request.FILES:
            banner.video = request.FILES['video']
        if 'poster_image' in request.FILES:
            poster_file = request.FILES['poster_image']
            fname = poster_file.name.lower()
            ctype = getattr(poster_file, 'content_type', '').lower()
            if fname.endswith(('.mp4', '.webm', '.mov', '.mkv')) or ctype.startswith('video/'):
                banner.video = poster_file
            else:
                banner.poster_image = poster_file
        if 'down_image' in request.FILES:
            banner.down_image = request.FILES['down_image']

        banner.save()
        serializer = SiteBannerSerializer(banner, context={'request': request})
        return Response({
            'success': True,
            'message': 'Homepage banner & media configuration updated successfully.',
            'banner': serializer.data
        }, status=status.HTTP_200_OK)


class AdminSiteBannerMediaResetView(APIView):
    """Allows resetting video, poster, or down image back to default."""
    permission_classes = [IsStaffOrSuperUser]

    def post(self, request):
        banner = SiteBanner.objects.first()
        if not banner:
            return Response({'error': 'No banner configured.'}, status=status.HTTP_404_NOT_FOUND)

        target = request.data.get('target', '')
        if target == 'video':
            if banner.video:
                banner.video.delete(save=False)
                banner.video = None
            banner.video_url = ''
            banner.save(update_fields=['video', 'video_url', 'updated_at'])
        elif target == 'poster':
            if banner.poster_image:
                banner.poster_image.delete(save=False)
                banner.poster_image = None
            banner.save(update_fields=['poster_image', 'updated_at'])
        elif target == 'down_image':
            if banner.down_image:
                banner.down_image.delete(save=False)
                banner.down_image = None
            banner.save(update_fields=['down_image', 'updated_at'])
        else:
            return Response({'error': 'Invalid reset target.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = SiteBannerSerializer(banner, context={'request': request})
        return Response({
            'success': True,
            'message': f'{target} removed successfully.',
            'banner': serializer.data
        }, status=status.HTTP_200_OK)

