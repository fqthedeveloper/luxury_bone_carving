from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from rest_framework.test import APIClient
from .models import Order, OrderItem, Product, UserProfile, Inquiry, CurrencyRate


class OrderAndAuthTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='collector@example.com',
            email='collector@example.com',
            password='SecretPassword123!',
            first_name='Arthur',
            last_name='Wellesley'
        )
        # Mark email verified for standard verified user tests
        self.user.profile.is_email_verified = True
        self.user.profile.save()

        self.staff_user = User.objects.create_user(
            username='admin@luxurybonecarving.com',
            email='admin@luxurybonecarving.com',
            password='StaffSecretPassword123!',
            is_staff=True,
            is_superuser=True
        )

        self.product = Product.objects.create(
            title='Imperial Dragon Bone Carving Box',
            slug='imperial-dragon-box',
            description='Masterpiece carved from ethically sourced bovine bone.',
            price_inr=Decimal('45000.00'),
            price_usd=Decimal('550.00'),
            sku='LBC-BOX-001',
            is_active=True
        )

    def test_email_password_login_verified(self):
        """Verify login for verified customer returns token and user profile."""
        res = self.client.post('/api/auth/login-password/', {
            'email': 'collector@example.com',
            'password': 'SecretPassword123!'
        }, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data.get('success'))
        self.assertIn('token', res.data)
        self.assertEqual(res.data['user']['email'], 'collector@example.com')

    def test_email_password_login_unverified_requires_otp(self):
        """Verify that an unverified customer logging in via password is asked for OTP verification."""
        unverified_user = User.objects.create_user(
            username='unverified@example.com',
            email='unverified@example.com',
            password='Password123!'
        )
        unverified_user.profile.is_email_verified = False
        unverified_user.profile.save()

        res = self.client.post('/api/auth/login-password/', {
            'email': 'unverified@example.com',
            'password': 'Password123!'
        }, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data.get('requires_otp'))
        self.assertEqual(res.data.get('email'), 'unverified@example.com')

    def test_email_otp_login_flow(self):
        """Verify requesting 6-digit OTP and verifying it logs the user in."""
        req_res = self.client.post('/api/auth/request-otp/', {
            'email': 'newcollector@example.com'
        }, format='json')
        self.assertEqual(req_res.status_code, 200)
        self.assertTrue(req_res.data.get('success'))

        user = User.objects.get(email='newcollector@example.com')
        otp = user.profile.otp
        self.assertTrue(bool(otp))
        self.assertEqual(len(otp), 6)

        verify_res = self.client.post('/api/auth/verify-otp-login/', {
            'email': 'newcollector@example.com',
            'otp': otp
        }, format='json')
        self.assertEqual(verify_res.status_code, 200)
        self.assertTrue(verify_res.data.get('success'))
        self.assertIn('token', verify_res.data)

    def test_order_creation_with_gateway_fee_and_24h_window(self):
        """Verify order creation calculates 2% gateway fee, total amount, and generates 24h token."""
        order_payload = {
            'customer_name': 'Arthur Wellesley',
            'email': 'collector@example.com',
            'phone': '+1 555 123 4567',
            'country': 'United Kingdom',
            'address_line1': '10 Downing St',
            'city': 'London',
            'postal_code': 'SW1A 2AA',
            'currency': 'USD',
            'shipping_amount': '0.00',
            'items': [
                {
                    'product_id': self.product.id,
                    'title': self.product.title,
                    'sku': self.product.sku,
                    'unit_price': '550.00',
                    'quantity': 2,
                    'image_url': 'https://example.com/image.jpg'
                }
            ]
        }
        res = self.client.post('/api/orders/', order_payload, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.data.get('success'))

        order_data = res.data['order']
        self.assertIn('order_number', order_data)
        self.assertTrue(order_data['order_number'].startswith('LBC-'))
        self.assertEqual(order_data['subtotal_amount'], '1100.00')
        # 2% fee on 1100.00 = 22.00
        self.assertEqual(order_data['gateway_fee'], '22.00')
        # Total = 1100.00 + 22.00 = 1122.00
        self.assertEqual(order_data['total_amount'], '1122.00')
        self.assertEqual(order_data['status'], 'pending_payment')
        self.assertFalse(order_data['is_expired'])
        self.assertGreater(order_data['seconds_remaining'], 86000)

        # Retrieve order via 24h payment token
        token = order_data['payment_token']
        get_res = self.client.get(f'/api/orders/pay/{token}/')
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.data['order_number'], order_data['order_number'])
        self.assertIn('gateways_available', get_res.data)
        self.assertTrue(get_res.data['gateways_available']['razorpay']['enabled'])

    def test_payment_verification(self):
        """Verify successful payment marks order as paid and records gateway reference."""
        order = Order.objects.create(
            customer_name='Arthur Wellesley',
            email='collector@example.com',
            country='United States',
            address_line1='5th Ave',
            city='New York',
            postal_code='10001',
            currency='USD',
            total_amount=Decimal('550.00'),
            payment_link_expires_at=timezone.now() + timedelta(hours=24)
        )

        res = self.client.post(f'/api/orders/pay/{order.payment_token}/verify/', {
            'gateway': 'razorpay',
            'payment_id': 'pay_test_verified123'
        }, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data.get('success'))
        self.assertEqual(res.data['order']['status'], 'paid')

        order.refresh_from_db()
        self.assertEqual(order.status, 'paid')
        self.assertEqual(order.payment_gateway, 'razorpay')
        self.assertEqual(order.gateway_payment_id, 'pay_test_verified123')

    def test_order_cancellation_and_admin_refund_flow(self):
        """Verify full lifecycle: customer requests cancel -> status becomes refund_requested -> admin refunds -> status becomes refunded."""
        order = Order.objects.create(
            customer_name='Lady Montagu',
            email='montagu@example.com',
            country='United Kingdom',
            address_line1='Piccadilly',
            city='London',
            postal_code='W1J 7NT',
            currency='USD',
            total_amount=Decimal('850.00'),
            status='paid',
            payment_gateway='razorpay',
            gateway_payment_id='pay_test_montagu_refund'
        )

        # 1. Customer requests cancellation
        cancel_res = self.client.post(f'/api/orders/pay/{order.payment_token}/request-cancel/', {
            'reason': 'Traveling abroad, require cancellation.'
        }, format='json')
        self.assertEqual(cancel_res.status_code, 200)
        self.assertTrue(cancel_res.data.get('success'))
        self.assertEqual(cancel_res.data['order']['status'], 'refund_requested')
        self.assertEqual(cancel_res.data['order']['cancellation_reason'], 'Traveling abroad, require cancellation.')

        # 2. Admin processes automated refund
        self.client.force_authenticate(user=self.staff_user)
        refund_res = self.client.post(f'/api/admin/orders/{order.id}/process-refund/', {
            'admin_notes': 'Approved by Concierge Director'
        }, format='json')
        self.assertEqual(refund_res.status_code, 200)
        self.assertTrue(refund_res.data.get('success'))
        self.assertEqual(refund_res.data['order']['status'], 'refunded')
        self.assertTrue(bool(refund_res.data['order']['refund_id']))

        order.refresh_from_db()
        self.assertEqual(order.status, 'refunded')
        self.assertEqual(order.refund_amount, Decimal('850.00'))

    def test_admin_reject_cancellation_request(self):
        """Verify admin can reject customer cancellation request, reverting status to paid."""
        order = Order.objects.create(
            customer_name='Lord Byron',
            email='byron@example.com',
            country='Greece',
            address_line1='Odos Syntagma',
            city='Athens',
            postal_code='10563',
            currency='EUR',
            total_amount=Decimal('450.00'),
            status='refund_requested',
            cancellation_reason='Changed mind'
        )

        self.client.force_authenticate(user=self.staff_user)
        reject_res = self.client.post(f'/api/admin/orders/{order.id}/reject-cancel/', {
            'admin_notes': 'Custom commission already in carving stage. Non-refundable.'
        }, format='json')
        self.assertEqual(reject_res.status_code, 200)
        self.assertTrue(reject_res.data.get('success'))
        self.assertEqual(reject_res.data['order']['status'], 'paid')

        order.refresh_from_db()
        self.assertEqual(order.status, 'paid')
        self.assertIn('Non-refundable', order.admin_refund_notes)

    def test_expired_24h_link_rejection(self):
        """Verify that past-due order links automatically transition to expired and reject payment."""
        order = Order.objects.create(
            customer_name='Lord Byron',
            email='byron@example.com',
            country='Greece',
            address_line1='Odos Syntagma',
            city='Athens',
            postal_code='10563',
            currency='EUR',
            total_amount=Decimal('450.00'),
            payment_link_expires_at=timezone.now() - timedelta(hours=2) # 2 hours expired
        )

        # 1. Fetching order marks status expired
        res = self.client.get(f'/api/orders/pay/{order.payment_token}/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], 'expired')
        self.assertTrue(res.data['is_expired'])
        self.assertEqual(res.data['seconds_remaining'], 0)

        # 2. Attempting to initiate payment on expired link returns 410 Gone
        init_res = self.client.post(f'/api/orders/pay/{order.payment_token}/initiate/', {
            'gateway': 'razorpay'
        }, format='json')
        self.assertEqual(init_res.status_code, 410)

    def test_inquiry_creation(self):
        """Verify submitting bespoke inquiry succeeds and saves record."""
        inquiry_payload = {
            'customer_name': 'Baroness Rothschild',
            'email': 'rothschild@example.com',
            'phone': '+44 20 7946 0991',
            'country': 'United Kingdom',
            'quantity': 1,
            'requirements': 'Requesting private consultation for custom dining set.',
            'product': self.product.id
        }
        res = self.client.post('/api/inquiries/', inquiry_payload, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['customer_name'], 'Baroness Rothschild')


class SecurityAndPermissionsTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create_user(
            username='regular@example.com',
            email='regular@example.com',
            password='Password123!'
        )
        self.staff_user = User.objects.create_user(
            username='admin@luxurybonecarving.com',
            email='admin@luxurybonecarving.com',
            password='StaffSecretPassword123!',
            is_staff=True,
            is_superuser=True
        )

    def test_anonymous_user_blocked_from_admin_stats(self):
        """Verify unauthenticated user cannot access admin stats (401/403)."""
        res = self.client.get('/api/admin/stats/')
        self.assertIn(res.status_code, [401, 403])

    def test_non_staff_user_blocked_from_admin_stats(self):
        """Verify non-staff authenticated customer is forbidden from admin stats (403)."""
        self.client.force_authenticate(user=self.customer)
        res = self.client.get('/api/admin/stats/')
        self.assertEqual(res.status_code, 403)

    def test_non_staff_user_blocked_from_admin_orders(self):
        """Verify non-staff authenticated customer cannot access admin orders list (403)."""
        self.client.force_authenticate(user=self.customer)
        res = self.client.get('/api/admin/orders/')
        self.assertEqual(res.status_code, 403)

    def test_staff_user_allowed_to_admin_stats(self):
        """Verify authenticated staff/superuser gets 200 OK on admin stats."""
        self.client.force_authenticate(user=self.staff_user)
        res = self.client.get('/api/admin/stats/')
        self.assertEqual(res.status_code, 200)
        self.assertIn('total_products', res.data)
        self.assertIn('total_orders', res.data)


class CatalogAndReviewTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.product = Product.objects.create(
            title='Royal Chess Set',
            slug='royal-chess-set',
            description='Handcrafted bovine bone chess pieces with intricate filigree.',
            price_inr=Decimal('75000.00'),
            price_usd=Decimal('900.00'),
            sku='LBC-CHESS-001',
            is_active=True,
            is_featured=True
        )

    def test_featured_products_list(self):
        """Verify featured products endpoint returns active featured items."""
        res = self.client.get('/api/products/featured/')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(len(res.data) > 0)
        self.assertEqual(res.data[0]['slug'], 'royal-chess-set')

    def test_product_detail_case_insensitive_slug(self):
        """Verify fetching product by slug is robust and case-insensitive."""
        res = self.client.get(f'/api/products/ROYAL-CHESS-SET/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['sku'], 'LBC-CHESS-001')

    def test_product_view_recording(self):
        """Verify recording product views increments view count."""
        initial_views = self.product.views_count
        res = self.client.post(f'/api/products/{self.product.slug}/view/')
        self.assertEqual(res.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.views_count, initial_views + 1)

    def test_site_banner_retrieval(self):
        """Verify active site banner endpoint returns configured hero banner."""
        res = self.client.get('/api/site-banners/')
        self.assertEqual(res.status_code, 200)
        self.assertIn('title', res.data)


class TranslationAndForexTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_translate_proxy_identity(self):
        """Verify translate proxy returns identical text when target matches source."""
        res = self.client.post('/api/translate/', {
            'q': 'Handcrafted Heritage',
            'target': 'en',
            'source': 'en'
        }, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data.get('translatedText'), 'Handcrafted Heritage')

    def test_translate_proxy_empty(self):
        """Verify translate proxy handles blank input safely without errors."""
        res = self.client.post('/api/translate/', {
            'q': '',
            'target': 'fr'
        }, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data.get('translatedText'), '')

    def test_currency_rates_list(self):
        """Verify currency-rates endpoint responds with currency rates list."""
        CurrencyRate.objects.get_or_create(currency_code='USD', defaults={'rate_to_usd': Decimal('1.0000')})
        CurrencyRate.objects.get_or_create(currency_code='EUR', defaults={'rate_to_usd': Decimal('0.9200')})
        res = self.client.get('/api/currency-rates/')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(isinstance(res.data, list))
        codes = [c['currency_code'] for c in res.data]
        self.assertIn('USD', codes)
