import requests
from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.views import APIView
from rest_framework.response import Response
from django.conf import settings
from django.db import models
from .models import Product, Category, Collection, CurrencyRate, Inquiry, SiteBanner
from .serializers import (
    ProductSerializer, CategorySerializer, CollectionSerializer,
    CurrencyRateSerializer, InquirySerializer, UserRegistrationSerializer,
    OTPVerifySerializer, SiteBannerSerializer
)
from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth.models import User
from .models import Product, UserProfile
from .email_utils import send_otp_email



class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

class OTPVerifyView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp = serializer.validated_data['otp']
            try:
                user = User.objects.get(email=email)
                profile = user.profile
                if profile.is_otp_valid(otp):
                    profile.is_email_verified = True
                    profile.otp = None
                    profile.otp_created_at = None
                    profile.save()
                    return Response({'detail': 'Email verified successfully.'}, status=status.HTTP_200_OK)
                else:
                    return Response({'detail': 'Invalid or expired OTP.'}, status=status.HTTP_400_BAD_REQUEST)
            except User.DoesNotExist:
                return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ResendOTPView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email')
        if not email:
            return Response({'detail': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(email=email)
            profile = user.profile
            if profile.is_email_verified:
                return Response({'detail': 'Email already verified.'}, status=status.HTTP_400_BAD_REQUEST)
            otp = profile.generate_otp()
            lang = request.data.get('language') or request.headers.get('Accept-Language', 'en').split(',')[0].strip()[:2].lower()
            send_otp_email(user, otp, lang=lang)
            return Response({'detail': 'OTP resent successfully.'}, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

class FeaturedProductList(generics.ListAPIView):
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return Product.objects.filter(is_active=True, is_featured=True)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['language'] = self.request.query_params.get('lang', 'en')
        return context


class TranslateProxyView(APIView):
    """
    Handles translation requests for static frontend text (e.g. 'Inquire Now', headers).
    """
    def post(self, request):
        text = request.data.get('q', '').strip()
        target_lang = request.data.get('target', 'en')
        source_lang = request.data.get('source', 'en')

        if not text or target_lang == source_lang:
            return Response({"translatedText": text}, status=status.HTTP_200_OK)

        from .translation_utils import translate_text
        translated = translate_text(text, target_lang, source_lang)
        return Response({"translatedText": translated}, status=status.HTTP_200_OK)


class ProductList(generics.ListAPIView):
    """List all products with optional filters and language context."""
    queryset = Product.objects.filter(is_active=True)
    serializer_class = ProductSerializer
    filterset_fields = ['category', 'collection']

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['language'] = self.request.query_params.get('lang', 'en')
        return context


class ProductDetail(generics.RetrieveAPIView):
    """Get product detail by slug (case-insensitive), with language parameter for translations."""
    queryset = Product.objects.filter(is_active=True)
    serializer_class = ProductSerializer

    def get_object(self):
        slug = self.kwargs.get('slug')
        product = Product.objects.filter(is_active=True).filter(
            models.Q(slug=slug) | models.Q(slug__iexact=slug)
        ).first()
        if not product:
            from rest_framework.exceptions import NotFound
            raise NotFound("Product not found.")
        return product

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['language'] = self.request.query_params.get('lang', 'en')
        return context


class CategoryList(generics.ListAPIView):
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['language'] = self.request.query_params.get('lang', 'en')
        return context


class CollectionList(generics.ListAPIView):
    queryset = Collection.objects.filter(is_active=True)
    serializer_class = CollectionSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['language'] = self.request.query_params.get('lang', 'en')
        return context


@api_view(['GET'])
def currency_rates(request):
    try:
        from .currency_updater import refresh_currency_rates_if_needed
        refresh_currency_rates_if_needed()
    except Exception as e:
        pass
    rates = CurrencyRate.objects.all()
    serializer = CurrencyRateSerializer(rates, many=True)
    return Response(serializer.data)


@api_view(['POST'])
def create_inquiry(request):
    serializer = InquirySerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SiteBannerView(APIView):
    """Public endpoint to fetch active homepage banner configuration."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        banner = SiteBanner.objects.filter(is_active=True).first()
        if not banner:
            # Fallback to create default record
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