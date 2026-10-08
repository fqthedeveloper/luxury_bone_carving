import requests
import logging
from decimal import Decimal
from django.utils import timezone
from .models import CurrencyRate

logger = logging.getLogger(__name__)

# List of target currencies to track against USD
CURRENCIES_TO_TRACK = ['INR', 'EUR', 'GBP', 'AED', 'AUD', 'CAD', 'SGD', 'JPY']

def refresh_currency_rates_if_needed(force=False):
    """
    Checks if rates are older than 12 hours (or force=True).
    Fetches real-time live forex rates automatically from public open exchange APIs
    without requiring any manual commands or cron configurations.
    """
    latest = CurrencyRate.objects.order_by('-updated_at').first()
    
    if not force and latest and latest.updated_at:
        age_hours = (timezone.now() - latest.updated_at).total_seconds() / 3600
        if age_hours < 12:
            # Rates are fresh within 12 hours, no fetch needed
            return False

    try:
        # Free open exchange rates endpoint (base USD)
        url = "https://open.er-api.com/v6/latest/USD"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            rates = data.get('rates', {})
            for code in CURRENCIES_TO_TRACK:
                if code in rates:
                    rate_val = Decimal(str(rates[code])).quantize(Decimal('0.0001'))
                    CurrencyRate.objects.update_or_create(
                        currency_code=code,
                        defaults={
                            'rate_to_usd': rate_val,
                        }
                    )
            logger.info("Successfully auto-updated live currency exchange rates from Open Exchange API.")
            return True
    except Exception as e:
        logger.warning(f"Could not auto-fetch live forex rates: {e}")
        # Fallback to secondary endpoint
        try:
            url_backup = "https://api.exchangerate-api.com/v4/latest/USD"
            res2 = requests.get(url_backup, timeout=5)
            if res2.status_code == 200:
                rates2 = res2.json().get('rates', {})
                for code in CURRENCIES_TO_TRACK:
                    if code in rates2:
                        rate_val = Decimal(str(rates2[code])).quantize(Decimal('0.0001'))
                        CurrencyRate.objects.update_or_create(
                            currency_code=code,
                            defaults={
                                'rate_to_usd': rate_val,
                            }
                        )
                return True
        except Exception as e2:
            logger.warning(f"Secondary forex rate fetch failed: {e2}")

    return False
