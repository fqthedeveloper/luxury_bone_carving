# main/signals.py

import threading
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import UserProfile, Inquiry, Product, Category, Collection
from .email_utils import send_otp_email, send_inquiry_confirmation, send_admin_inquiry_notification
from .translation_utils import (
    translate_product_to_all_languages,
    translate_category_to_all_languages,
    translate_collection_to_all_languages,
)

import sys

def _run_in_background(target, *args):
    """Helper to dispatch background tasks without blocking HTTP request cycles."""
    if 'test' in sys.argv:
        # In test suite, do not run concurrent thread database writes on SQLite
        return
    t = threading.Thread(target=target, args=args, daemon=True)
    t.start()

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        profile = UserProfile.objects.create(user=instance)
        otp = profile.generate_otp()
        _run_in_background(send_otp_email, instance, otp)

@receiver(post_save, sender=Inquiry)
def handle_inquiry_created(sender, instance, created, **kwargs):
    if created:
        _run_in_background(send_inquiry_confirmation, instance)
        _run_in_background(send_admin_inquiry_notification, instance)

@receiver(post_save, sender=Product)
def auto_translate_product_on_save(sender, instance, created, **kwargs):
    """
    Automatically translate product title, description, and specifications
    across all supported languages whenever admin saves or updates a product.
    Dispatched in background thread so admin save is instantaneous.
    """
    _run_in_background(translate_product_to_all_languages, instance)

@receiver(post_save, sender=Category)
def auto_translate_category_on_save(sender, instance, created, **kwargs):
    """Automatically translate category name and description on save in background."""
    _run_in_background(translate_category_to_all_languages, instance)

@receiver(post_save, sender=Collection)
def auto_translate_collection_on_save(sender, instance, created, **kwargs):
    """Automatically translate collection name and description on save in background."""
    _run_in_background(translate_collection_to_all_languages, instance)