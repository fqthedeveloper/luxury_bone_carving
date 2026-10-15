# core/email_utils.py
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

_EMAIL_CACHE = {}

def get_email_translations(lang='en'):
    """
    Returns localized strings for customer emails.
    Caches translations in-memory per language.
    """
    if not lang or lang.lower() == 'en':
        return {}
    lang = lang.lower()
    if lang in _EMAIL_CACHE:
        return _EMAIL_CACHE[lang]

    phrases = {
        'brand_subtitle': "Artisanal Heritage & Bespoke Craft",
        'reservation_active': "Reservation Window Active",
        'order_ref': "Order Reference",
        'reservation_notice': "Your artisanal piece has been reserved exclusively for you. To secure craftsmanship and worldwide insured dispatch, please complete payment within the next 24 hours.",
        'dear': "Dear",
        'order_thank_you': "Thank you for your valued order. Our master artisans have reviewed your request. Below is your curated order summary:",
        'item': "Item",
        'qty': "Qty",
        'amount': "Amount",
        'subtotal': "Subtotal",
        'shipping': "Worldwide Insured Shipping",
        'complimentary': "Complimentary",
        'total': "Total",
        'pay_button': "Complete Secure Payment",
        'payment_expires_on': "Payment link expires on:",
        'paste_link': "Or copy and paste this link in your browser:",
        'ethical_notice': "Ethically Sourced Bovine & Camel Bone • 100% CITES Exempt • Global Insured Courier",
        'bespoke_queries': "For bespoke queries, reply directly or reach our concierge at concierge@luxurybonecarving.com",
        'payment_confirmed': "Payment Confirmed",
        'payment_confirmed_msg': "Your payment has been received successfully via Secure Gateway.",
        'crafting_notice': "Our master craftsmen have initiated preparation and secure export packaging for your collection piece. As soon as your shipment is dispatched with DHL Express / FedEx Priority, you will receive an international tracking code and CITES compliance documentation.",
        'destination': "Delivery Destination",
        'concierge_support': "Concierge Support • worldwide.support@luxurybonecarving.com",
        'cancel_requested': "Cancellation & Refund Requested",
        'cancel_received_msg': "we have received your cancellation and refund request for this order.",
        'request_details': "Request Details",
        'total_paid': "Total Paid",
        'reason_provided': "Reason provided",
        'cancel_review_msg': "Our concierge team is reviewing your request. If approved, your full refund will be processed immediately via Razorpay back to your original source of payment (bank, credit/debit card, UPI, or wallet), and you will receive an instant confirmation receipt.",
        'refund_processed': "Refund Processed",
        'refund_credited_msg': "your refund has been initiated and credited back to your original payment account.",
        'refund_details': "Refund Transaction Details",
        'refund_ref_id': "Refund Reference ID",
        'refunded_amount': "Refunded Amount",
        'settlement_dest': "Settlement Destination",
        'settlement_note': "Original payment source (Card / UPI / Bank Account / Wallet)",
        'refund_timeline': "Depending on your banking institution or card issuer, the credited balance typically reflects on your statement within 5 to 7 business days (instant for UPI / wallets). If you have any questions, our concierge team is always here for you.",
        'inquiry_thank_you': "Thank you for your inquiry",
        'inquiry_received': "We have received your inquiry regarding",
        'inquiry_review_msg': "Our team will review your request and get back to you within 24 hours.",
        'inquiry_help': "If you need immediate assistance, please contact us at",
        'auto_msg': "This is an automated message. Please do not reply directly to this email.",
        'inquiry_team_responded': "Thank you for your inquiry. Our team has responded:",
        'further_questions': "If you have further questions, please reply to this email."
    }

    try:
        from .translation_utils import translate_text
        translated = {}
        for k, text in phrases.items():
            translated[k] = translate_text(text, target_lang=lang)
        _EMAIL_CACHE[lang] = translated
        return translated
    except Exception as e:
        logger.warning(f"Failed to generate email translations for {lang}: {e}")
        return {}


def send_html_email(subject, html_template, context, recipient_list, from_email=None, lang='en'):
    """
    Send an HTML email using a template with optional language localization.
    context: dictionary of variables for the template.
    """
    if from_email is None:
        from_email = settings.DEFAULT_FROM_EMAIL

    if lang and lang.lower() != 'en':
        try:
            from .translation_utils import translate_text
            subject = translate_text(subject, target_lang=lang)
            if 'i18n' not in context:
                context['i18n'] = get_email_translations(lang)
        except Exception as e:
            logger.warning(f"Failed to localize email subject for {lang}: {e}")

    html_content = render_to_string(html_template, context)
    text_content = strip_tags(html_content)   # fallback plain text

    msg = EmailMultiAlternatives(subject, text_content, from_email, recipient_list)
    msg.attach_alternative(html_content, "text/html")
    try:
        msg.send()
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def send_inquiry_confirmation(inquiry, lang=None):
    """Send confirmation email to customer after inquiry submission."""
    if not lang:
        lang = getattr(inquiry, 'language', None) or 'en'
    subject = f"Your Inquiry #{inquiry.id} – Luxury Bone Carving"
    context = {
        'inquiry': inquiry,
        'site_name': 'Luxury Bone Carving',
    }
    return send_html_email(
        subject,
        'email/inquiry_confirmation.html',
        context,
        [inquiry.email],
        lang=lang
    )


def send_admin_inquiry_notification(inquiry):
    """Send notification email to admin(s) about new inquiry (Rule A1: stays English)."""
    subject = f"New Inquiry #{inquiry.id} from {inquiry.customer_name}"
    context = {
        'inquiry': inquiry,
        'admin_url': settings.ADMIN_URL or '/admin/',
    }
    admin_emails = settings.ADMIN_EMAILS
    return send_html_email(
        subject,
        'email/admin_inquiry_notification.html',
        context,
        admin_emails,
        lang='en'
    )


def send_inquiry_reply_email(reply, inquiry, lang=None):
    """Send email to customer when admin replies."""
    if not lang:
        lang = getattr(inquiry, 'language', None) or 'en'
    subject = f"Re: Your Inquiry #{inquiry.id} – Luxury Bone Carving"
    context = {
        'inquiry': inquiry,
        'reply': reply,
        'site_name': 'Luxury Bone Carving',
    }
    return send_html_email(
        subject,
        'email/reply_to_customer.html',
        context,
        [inquiry.email],
        lang=lang
    )


def send_otp_email(user, otp, lang='en'):
    """Send one-time password to customer in their preferred language."""
    subject = 'Your OTP for Email Verification - Luxury Bone Carving'
    message = f'Hello {user.username},\n\nYour one-time verification code is: {otp}\n\nThis OTP is valid for {settings.OTP_EXPIRY_SECONDS // 60} minutes.\n\nThank you,\nLuxury Bone Carving'

    if lang and lang.lower() != 'en':
        try:
            from .translation_utils import translate_text
            subject = translate_text(subject, target_lang=lang)
            greeting = translate_text(f"Hello {user.username}", target_lang=lang)
            code_msg = translate_text("Your one-time verification code is:", target_lang=lang)
            valid_msg = translate_text(f"This OTP is valid for {settings.OTP_EXPIRY_SECONDS // 60} minutes.", target_lang=lang)
            closing = translate_text("Thank you,\nLuxury Bone Carving", target_lang=lang)
            message = f"{greeting},\n\n{code_msg} {otp}\n\n{valid_msg}\n\n{closing}"
        except Exception as e:
            logger.warning(f"Failed to translate OTP email: {e}")

    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [user.email]
    try:
        send_mail(subject, message, from_email, recipient_list, fail_silently=False)
        return True
    except Exception as e:
        logger.error(f"Failed to send OTP email: {e}")
        return False


def send_order_payment_link_email(order, payment_url, lang=None):
    """Send luxury 24-hour payment link email to customer."""
    if not lang:
        lang = getattr(order, 'language', None) or 'en'
    subject = f"Reserved: Your 24-Hour Payment Link for Order #{order.order_number}"
    context = {
        'order': order,
        'payment_url': payment_url,
        'site_name': 'Luxury Bone Carving',
    }
    return send_html_email(
        subject,
        'email/order_payment_link.html',
        context,
        [order.email],
        lang=lang
    )


def send_order_payment_success_email(order, lang=None):
    """Send payment receipt and confirmation email."""
    if not lang:
        lang = getattr(order, 'language', None) or 'en'
    subject = f"Payment Confirmed - Order #{order.order_number} (Luxury Bone Carving)"
    context = {
        'order': order,
        'site_name': 'Luxury Bone Carving',
    }
    return send_html_email(
        subject,
        'email/order_payment_success.html',
        context,
        [order.email],
        lang=lang
    )


def send_cancellation_request_email(order, lang=None):
    """Notify customer that cancellation request is received and alert concierge."""
    if not lang:
        lang = getattr(order, 'language', None) or 'en'
    subject = f"Cancellation Request Received - Order #{order.order_number}"
    context = {
        'order': order,
        'site_name': 'Luxury Bone Carving',
    }
    # Customer confirmation (in customer's language)
    send_html_email(
        subject,
        'email/order_cancel_requested.html',
        context,
        [order.email],
        lang=lang
    )
    # Concierge alert (Rule A1: stays English for staff)
    admin_emails = getattr(settings, 'ADMIN_EMAILS', [settings.DEFAULT_FROM_EMAIL])
    return send_html_email(
        f"Concierge Alert: Refund Requested for Order #{order.order_number}",
        'email/admin_cancel_alert.html',
        context,
        admin_emails,
        lang='en'
    )


def send_refund_confirmed_email(order, lang=None):
    """Send official refund and reversal receipt to customer."""
    if not lang:
        lang = getattr(order, 'language', None) or 'en'
    subject = f"Refund Processed & Reversed - Order #{order.order_number} (Luxury Bone Carving)"
    context = {
        'order': order,
        'site_name': 'Luxury Bone Carving',
    }
    return send_html_email(
        subject,
        'email/order_refund_success.html',
        context,
        [order.email],
        lang=lang
    )