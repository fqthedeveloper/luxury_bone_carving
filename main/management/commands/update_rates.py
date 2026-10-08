import requests
from decimal import Decimal
from django.core.management.base import BaseCommand
from main.models import CurrencyRate

class Command(BaseCommand):
    help = 'Fetch latest exchange rates from USD to other currencies'

    def handle(self, *args, **options):
        # Using free exchange rate API (e.g., exchangerate-api.com)
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            rates = data.get('rates', {})
            # Only update currencies that we support (from settings)
            supported_codes = ['INR', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'SGD', 'AED', 'CHF', 'CNY', 'NZD']
            for code in supported_codes:
                if code in rates:
                    rate = Decimal(str(rates[code]))
                    CurrencyRate.objects.update_or_create(
                        currency_code=code,
                        defaults={'rate_to_usd': rate}
                    )
                    self.stdout.write(f"Updated {code}: {rate}")
            self.stdout.write(self.style.SUCCESS('Successfully updated rates.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {e}'))