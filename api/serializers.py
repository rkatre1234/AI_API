from rest_framework import serializers
from .models import Product, UploadedFile

class FileUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadedFile
        fields = '__all__'
        

class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = '__all__'
        
class ResumeParserSerializer(serializers.Serializer):
    resume_text = serializers.CharField()
    
class JobSearchSerializer(serializers.Serializer):
    job_title = serializers.CharField(required=True)
    skills = serializers.ListField(child=serializers.CharField(), required=False)
    experience = serializers.FloatField(required=False)
    location = serializers.CharField(required=False)
    employment_type = serializers.CharField(required=False)
