from rest_framework import serializers
from .models import Product

class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = '__all__'
class ResumeParserSerializer(serializers.Serializer):
    resume_text = serializers.CharField()
  