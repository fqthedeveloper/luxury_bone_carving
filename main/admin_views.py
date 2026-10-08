from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.db.models import Count, Sum
from .models import Product, Inquiry, Category, Collection

@staff_member_required
def dashboard(request):
    context = {
        'total_products': Product.objects.count(),
        'active_products': Product.objects.filter(is_active=True).count(),
        'total_inquiries': Inquiry.objects.count(),
        'new_inquiries': Inquiry.objects.filter(status='new').count(),
        'total_categories': Category.objects.count(),
        'total_collections': Collection.objects.count(),
        'recent_inquiries': Inquiry.objects.order_by('-created_at')[:10],
        'top_products': Product.objects.annotate(
            inquiry_count=Count('inquiry')
        ).order_by('-inquiry_count')[:5],
    }
    return render(request, 'admin/main/dashboard.html', context)