from django.urls import path
from .views import ProductListCreateView, ProductDetailView
from .views import ResumeParserView

urlpatterns = [
    path('products/', ProductListCreateView.as_view(), name='product-list-create'),
    path('products/<int:pk>/', ProductDetailView.as_view(), name='product-detail'),
    path('parse-resume/', ResumeParserView.as_view(), name='parse-resume'),
]