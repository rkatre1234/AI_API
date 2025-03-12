from rest_framework import serializers
from .models import Product, UploadedFile

class FileUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadedFile
        fields = ['file']

class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = '__all__'
        
class ResumeParserSerializer(serializers.Serializer):
    resume_text = serializers.CharField()
  