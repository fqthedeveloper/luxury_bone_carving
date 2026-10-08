# core/email_utils.py
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def send_html_email(subject, html_template, context, recipient_list, from_email=None):
    """
    Send an HTML email using a template.
    context: dictionary of variables for the template.
    """
    if from_email is None:
        from_email = settings.DEFAULT_FROM_EMAIL

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

def send_inquiry_confirmation(inquiry):
    """Send confirmation email to customer after inquiry submission."""
    subject = f"Your Inquiry #{inquiry.id} – Luxury Bone Carving"
    context = {
        'inquiry': inquiry,
        'site_name': 'Luxury Bone Carving',
    }
    return send_html_email(
        subject,
        'email/inquiry_confirmation.html',
        context,
        [inquiry.email]
    )

def send_admin_inquiry_notification(inquiry):
    """Send notification email to admin(s) about new inquiry."""
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
        admin_emails
    )

def send_inquiry_reply_email(reply, inquiry):
    """Send email to customer when admin replies."""
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
        [inquiry.email]
    )
    

def send_otp_email(user, otp):
    subject = 'Your OTP for Email Verification - Luxury Bone Carving'
    message = f'Hello {user.username},\n\nYour one-time verification code is: {otp}\n\nThis OTP is valid for {settings.OTP_EXPIRY_SECONDS // 60} minutes.\n\nThank you,\nLuxury Bone Carving'
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [user.email]
    try:
        send_mail(subject, message, from_email, recipient_list, fail_silently=False)
        return True
    except Exception as e:
        logger.error(f"Failed to send OTP email: {e}")
        return False


def send_order_payment_link_email(order, payment_url):
    """Send luxury 24-hour payment link email to customer."""
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
        [order.email]
    )


def send_order_payment_success_email(order):
    """Send payment receipt and confirmation email."""
    subject = f"Payment Confirmed - Order #{order.order_number} (Luxury Bone Carving)"
    context = {
        'order': order,
        'site_name': 'Luxury Bone Carving',
    }
    return send_html_email(
        subject,
        'email/order_payment_success.html',
        context,
        [order.email]
    )


def send_cancellation_request_email(order):
    """Notify customer that cancellation request is received and alert concierge."""
    subject = f"Cancellation Request Received - Order #{order.order_number}"
    context = {
        'order': order,
        'site_name': 'Luxury Bone Carving',
    }
    # Customer confirmation
    send_html_email(
        subject,
        'email/order_cancel_requested.html',
        context,
        [order.email]
    )
    # Concierge alert
    admin_emails = getattr(settings, 'ADMIN_EMAILS', [settings.DEFAULT_FROM_EMAIL])
    return send_html_email(
        f"Concierge Alert: Refund Requested for Order #{order.order_number}",
        'email/admin_cancel_alert.html',
        context,
        admin_emails
    )


def send_refund_confirmed_email(order):
    """Send official refund and reversal receipt to customer."""
    subject = f"Refund Processed & Reversed - Order #{order.order_number} (Luxury Bone Carving)"
    context = {
        'order': order,
        'site_name': 'Luxury Bone Carving',
    }
    return send_html_email(
        subject,
        'email/order_refund_success.html',
        context,
        [order.email]
    )