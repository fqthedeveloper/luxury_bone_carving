from django.core.management.base import BaseCommand
from main.models import Product, Category, Collection
from main.translation_utils import (
    translate_product_to_all_languages,
    translate_category_to_all_languages,
    translate_collection_to_all_languages,
)

class Command(BaseCommand):
    help = "Automatically translates all Products, Categories, and Collections into supported languages."

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force re-translation of objects even if translations already exist.',
        )

    def handle(self, *args, **options):
        force = options['force']
        
        self.stdout.write(self.style.WARNING("Starting batch translation..."))

        # 1. Translate Products
        products = Product.objects.all()
        self.stdout.write(f"Processing {products.count()} products...")
        for product in products:
            if force or not product.translations.exists():
                translate_product_to_all_languages(product)
                self.stdout.write(self.style.SUCCESS(f"  [+] Translated Product: {product.title}"))

        # 2. Translate Categories
        categories = Category.objects.all()
        self.stdout.write(f"Processing {categories.count()} categories...")
        for category in categories:
            if force or not category.translations.exists():
                translate_category_to_all_languages(category)
                self.stdout.write(self.style.SUCCESS(f"  [+] Translated Category: {category.name}"))

        # 3. Translate Collections
        collections = Collection.objects.all()
        self.stdout.write(f"Processing {collections.count()} collections...")
        for collection in collections:
            if force or not collection.translations.exists():
                translate_collection_to_all_languages(collection)
                self.stdout.write(self.style.SUCCESS(f"  [+] Translated Collection: {collection.name}"))

        self.stdout.write(self.style.SUCCESS("All objects processed successfully!"))