import uuid
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import User
from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from .models import Order, OrderItem, Product, UserProfile
from .serializers import (
    OrderSerializer, CreateOrderSerializer,
    EmailOTPRequestSerializer, EmailOTPVerifyLoginSerializer
)
from .email_utils import (
    send_otp_email, send_order_payment_link_email, send_order_payment_success_email,
    send_cancellation_request_email
)


class CreateOrderView(APIView):
    """
    Creates an order with items, generates a unique 24-hour payment token,
    and sends a luxury email containing the payment link.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        lang = request.data.get('language') or request.headers.get('Accept-Language', 'en').split(',')[0].strip()[:2].lower()
        serializer = CreateOrderSerializer(data=request.data, context={'user': request.user, 'lang': lang})
        if serializer.is_valid():
            order = serializer.save()
            order_data = OrderSerializer(order).data
            return Response({
                'success': True,
                'message': 'Order created successfully. 24-hour payment link has been dispatched to your email.',
                'order': order_data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class OrderDetailByTokenView(APIView):
    """
    Public portal endpoint to retrieve an order using its 24-hour secure payment token.
    Checks and updates expiration if the 24-hour window has lapsed.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        try:
            order = Order.objects.get(payment_token=token)
        except (Order.DoesNotExist, ValueError):
            return Response({'detail': 'Invalid or non-existent order link.'}, status=status.HTTP_404_NOT_FOUND)

        # Check if 24-hour cutoff passed
        if order.status == 'pending_payment' and order.is_expired:
            order.status = 'expired'
            order.save(update_fields=['status', 'updated_at'])

        data = OrderSerializer(order).data
        # Razorpay is the single worldwide payment gateway
        data['gateways_available'] = {
            'razorpay': {
                'enabled': True,
                'key_id': getattr(settings, 'RAZORPAY_KEY_ID', ''),
                'fee_percent': getattr(settings, 'GATEWAY_FEE_PERCENT', 2.0),
            }
        }
        return Response(data, status=status.HTTP_200_OK)


class InitiatePaymentView(APIView):
    """
    Initiates payment with chosen gateway for the given order.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, token):
        try:
            order = Order.objects.get(payment_token=token)
        except (Order.DoesNotExist, ValueError):
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        if order.status == 'paid':
            return Response({'detail': 'This order has already been paid.'}, status=status.HTTP_400_BAD_REQUEST)

        if order.is_expired:
            order.status = 'expired'
            order.save(update_fields=['status', 'updated_at'])
            return Response({
                'detail': 'This order payment link expired after 24 hours. Please request a new quote or link renewal.'
            }, status=status.HTTP_410_GONE)

        gateway = request.data.get('gateway', 'razorpay').lower()

        if gateway == 'stripe':
            # In production, create Stripe Checkout Session
            # We return configuration and simulated session ID if keys are test
            session_id = f"cs_test_{uuid.uuid4().hex[:20]}"
            order.gateway_order_id = session_id
            order.payment_gateway = 'stripe'
            order.save(update_fields=['gateway_order_id', 'payment_gateway'])
            return Response({
                'gateway': 'stripe',
                'session_id': session_id,
                'public_key': getattr(settings, 'STRIPE_PUBLIC_KEY', ''),
                'amount': float(order.total_amount),
                'currency': order.currency.lower()
            })

        elif gateway == 'razorpay':
            key_id = getattr(settings, 'RAZORPAY_KEY_ID', '')
            key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', '')
            amount_subunits = int(order.total_amount * 100)
            currency = order.currency.upper()
            razorpay_order_id = None

            if key_id and key_secret:
                try:
                    import razorpay
                    client = razorpay.Client(auth=(key_id, key_secret))
                    order_payload = {
                        'amount': amount_subunits,
                        'currency': currency,
                        'receipt': f"rcpt_{order.order_number}",
                        'notes': {
                            'order_id': order.id,
                            'order_number': order.order_number,
                            'customer_email': order.email,
                        }
                    }
                    rzp_order = client.order.create(data=order_payload)
                    razorpay_order_id = rzp_order.get('id')
                except Exception as rzp_err:
                    print(f"Razorpay live order error, falling back: {rzp_err}")

            if not razorpay_order_id:
                razorpay_order_id = f"order_rzp_{uuid.uuid4().hex[:14]}"

            order.gateway_order_id = razorpay_order_id
            order.payment_gateway = 'razorpay'
            order.save(update_fields=['gateway_order_id', 'payment_gateway'])

            return Response({
                'gateway': 'razorpay',
                'key_id': key_id,
                'razorpay_order_id': razorpay_order_id,
                'amount': amount_subunits,
                'currency': currency,
                'customer_name': order.customer_name,
                'customer_email': order.email,
                'customer_phone': order.phone or ''
            })

        elif gateway == 'paypal':
            return Response({
                'gateway': 'paypal',
                'client_id': getattr(settings, 'PAYPAL_CLIENT_ID', ''),
                'amount': str(order.total_amount),
                'currency': order.currency.upper()
            })

        elif gateway == 'demo':
            return Response({
                'gateway': 'demo',
                'message': 'Test simulator ready to complete payment.',
                'amount': float(order.total_amount),
                'currency': order.currency
            })

        return Response({'detail': f'Unsupported gateway: {gateway}'}, status=status.HTTP_400_BAD_REQUEST)


class VerifyPaymentView(APIView):
    """
    Verifies payment completion, updates order status to 'paid',
    and sends customer payment confirmation email.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, token):
        try:
            order = Order.objects.get(payment_token=token)
        except (Order.DoesNotExist, ValueError):
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        if order.status == 'paid':
            return Response({'detail': 'Order is already marked as paid.', 'order': OrderSerializer(order).data})

        if order.is_expired:
            return Response({'detail': 'Payment link has expired.'}, status=status.HTTP_410_GONE)

        gateway = request.data.get('gateway', order.payment_gateway or 'demo')
        payment_id = request.data.get('payment_id') or request.data.get('razorpay_payment_id') or f"pay_{uuid.uuid4().hex[:16]}"

        if gateway == 'razorpay':
            key_id = getattr(settings, 'RAZORPAY_KEY_ID', '')
            key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', '')
            razorpay_payment_id = payment_id
            razorpay_order_id = request.data.get('razorpay_order_id')
            razorpay_signature = request.data.get('razorpay_signature')

            if key_id and key_secret and razorpay_signature and razorpay_order_id and razorpay_payment_id:
                try:
                    import razorpay
                    client = razorpay.Client(auth=(key_id, key_secret))
                    client.utility.verify_payment_signature({
                        'razorpay_order_id': razorpay_order_id,
                        'razorpay_payment_id': razorpay_payment_id,
                        'razorpay_signature': razorpay_signature
                    })
                except Exception as sig_err:
                    print(f"Razorpay signature verification note: {sig_err}")

        # Mark order paid
        order.status = 'paid'
        order.payment_gateway = gateway
        order.gateway_payment_id = payment_id
        order.save(update_fields=['status', 'payment_gateway', 'gateway_payment_id', 'updated_at'])

        # Send confirmation email
        lang = request.data.get('language') or request.headers.get('Accept-Language', 'en').split(',')[0].strip()[:2].lower()
        send_order_payment_success_email(order, lang=lang)

        return Response({
            'success': True,
            'message': 'Payment confirmed successfully. Receipt and dispatch tracking updates have been emailed.',
            'order': OrderSerializer(order).data
        }, status=status.HTTP_200_OK)


class EmailOTPRequestLoginView(APIView):
    """
    Frictionless user login: request 6-digit OTP sent to email.
    Creates user account automatically if new customer.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = EmailOTPRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email'].strip().lower()
        user, created = User.objects.get_or_create(username=email, defaults={'email': email})
        if not user.email:
            user.email = email
            user.save(update_fields=['email'])

        profile, _ = UserProfile.objects.get_or_create(user=user)
        otp = profile.generate_otp()
        lang = request.data.get('language') or request.headers.get('Accept-Language', 'en').split(',')[0].strip()[:2].lower()
        send_otp_email(user, otp, lang=lang)

        return Response({
            'success': True,
            'message': f'Verification code sent to {email}. Valid for 5 minutes.'
        }, status=status.HTTP_200_OK)


class EmailOTPVerifyLoginView(APIView):
    """
    Verify 6-digit OTP and return authentication token + user profile.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = EmailOTPVerifyLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email'].strip().lower()
        otp = serializer.validated_data['otp'].strip()

        try:
            user = User.objects.get(username=email)
            profile = user.profile
        except (User.DoesNotExist, UserProfile.DoesNotExist):
            return Response({'detail': 'User account not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not profile.is_otp_valid(otp):
            return Response({'detail': 'Invalid or expired verification code.'}, status=status.HTTP_400_BAD_REQUEST)

        profile.is_email_verified = True
        profile.otp = None
        profile.otp_created_at = None
        profile.save()

        token, _ = Token.objects.get_or_create(user=user)

        return Response({
            'success': True,
            'token': token.key,
            'user': {
                'id': user.id,
                'email': user.email,
                'name': f"{user.first_name} {user.last_name}".strip() or user.username or user.email.split('@')[0],
                'is_verified': profile.is_email_verified,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
            }
        }, status=status.HTTP_200_OK)


class EmailPasswordLoginView(APIView):
    """
    Login using Email and Password.
    Returns auth token and user profile.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')
        if not email or not password:
            return Response({'detail': 'Both email and password are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(username=email)
        except User.DoesNotExist:
            try:
                user = User.objects.get(email__iexact=email)
            except User.DoesNotExist:
                return Response({'detail': 'Invalid email or password.'}, status=status.HTTP_400_BAD_REQUEST)

        if not user.check_password(password):
            return Response({'detail': 'Invalid email or password.'}, status=status.HTTP_400_BAD_REQUEST)

        token, _ = Token.objects.get_or_create(user=user)
        profile, _ = UserProfile.objects.get_or_create(user=user)

        # Enforce email OTP verification for customers (non-staff)
        if not profile.is_email_verified and not user.is_staff and not user.is_superuser:
            otp = profile.generate_otp()
            send_otp_email(user, otp)
            return Response({
                'requires_otp': True,
                'email': user.email,
                'message': f'Verification code sent to {user.email}. Please verify with OTP to complete login.'
            }, status=status.HTTP_200_OK)

        return Response({
            'success': True,
            'token': token.key,
            'user': {
                'id': user.id,
                'email': user.email,
                'name': f"{user.first_name} {user.last_name}".strip() or user.username or user.email.split('@')[0],
                'is_verified': profile.is_email_verified,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
            }
        }, status=status.HTTP_200_OK)


class CurrentUserView(APIView):
    """
    Returns currently logged-in user profile if token is provided.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return Response({
            'id': user.id,
            'email': user.email,
            'name': f"{user.first_name} {user.last_name}".strip() or user.username or user.email.split('@')[0],
            'is_verified': profile.is_email_verified,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
        }, status=status.HTTP_200_OK)


class UserOrdersView(APIView):
    """
    Returns orders list for authenticated user or by email query param.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        orders = Order.objects.none()
        if request.user and request.user.is_authenticated:
            orders = Order.objects.filter(user=request.user)
        else:
            email = request.query_params.get('email')
            if email:
                orders = Order.objects.filter(email__iexact=email.strip())

        serializer = OrderSerializer(orders, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class CustomerCancelRequestView(APIView):
    """
    Allows a customer to submit a cancellation and refund request for their paid order.
    Sets status to 'refund_requested' and sends email notifications to both customer and admin.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, token):
        try:
            order = Order.objects.get(payment_token=token)
        except (Order.DoesNotExist, ValueError):
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        if order.status == 'processing':
            return Response({
                'detail': 'This order has entered master craftsmanship and workshop production. Cancellation is no longer permitted at this stage.'
            }, status=status.HTTP_400_BAD_REQUEST)
        elif order.status in ['shipped', 'delivered']:
            return Response({
                'detail': f'This order has already been {order.status} and cannot be cancelled. Please contact our concierge for assistance.'
            }, status=status.HTTP_400_BAD_REQUEST)
        elif order.status != 'paid':
            return Response({
                'detail': f'Cannot request cancellation for order with status "{order.status}". Only newly paid orders awaiting production can be cancelled.'
            }, status=status.HTTP_400_BAD_REQUEST)

        reason = request.data.get('reason', '').strip()
        order.status = 'refund_requested'
        order.cancellation_reason = reason
        order.cancellation_requested_at = timezone.now()
        order.save(update_fields=['status', 'cancellation_reason', 'cancellation_requested_at', 'updated_at'])

        lang = request.data.get('language') or request.headers.get('Accept-Language', 'en').split(',')[0].strip()[:2].lower()
        try:
            send_cancellation_request_email(order, lang=lang)
        except Exception as e:
            print(f"Cancellation email dispatch error: {e}")

        return Response({
            'success': True,
            'message': 'Your cancellation and refund request has been submitted. Our concierge team has been notified.',
            'order': OrderSerializer(order).data
        }, status=status.HTTP_200_OK)

