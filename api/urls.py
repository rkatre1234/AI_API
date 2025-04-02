from django.urls import path
from .views import ProductListCreateView, ProductDetailView
from .views import ResumeParserView
from api.pages.test_views import TestView, GeminiView, FileUploadView, GoogleDriveToS3View
from rest_framework.routers import DefaultRouter


urlpatterns = [
    path('products/', ProductListCreateView.as_view(), name='product-list-create'),
    path('products/<int:pk>/', ProductDetailView.as_view(), name='product-detail'),
    path('parse-resume/', ResumeParserView.as_view(), name='parse-resume'),
    path('test/', TestView.as_view(), name='test'),
    path('gemini/', GeminiView.as_view(), name='gemini-api'),  # New API
    path('gemini-parse-resume/', GeminiView.as_view(), name='gemini-parse-resume'),
    path('upload/', FileUploadView.as_view(), name='file-upload'),
    path('google-drive-to-s3/', GoogleDriveToS3View.as_view(), name='google_drive_to_s3'),
]

