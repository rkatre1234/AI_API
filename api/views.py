from django.shortcuts import render
# resume parser
import json
import requests
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from .serializers import ResumeParserSerializer

# Create your views here.
from rest_framework import generics
from .models import Product
from .serializers import ProductSerializer

class ProductListCreateView(generics.ListCreateAPIView):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer

class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer

class ResumeParserView(APIView):
    def post(self, request):
        serializer = ResumeParserSerializer(data=request.data)
        if serializer.is_valid():
            resume_text = serializer.validated_data["resume_text"]

            try:
                # Sending request to Ollama API
                response = requests.post(
                    "http://localhost:11434/api/generate",
                    json={
                        "model": "llama2",
                        "prompt": f"Extract structured details like name, email, phone, skills, experience, and education from this resume:\n{resume_text}",
                        "stream": False  # Disable streaming to ensure JSON response
                    }
                )

                # Print raw response (for debugging)
                print("Raw Response:", response.text)

                # Ensure the response is valid JSON
                try:
                    response_json = response.json()
                except json.JSONDecodeError as e:
                    return Response(
                        {"error": f"Invalid JSON response from Ollama: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

                # Extract the response text
                if response.status_code == 200:
                    parsed_data = response_json.get("response", "No data extracted")
                    return Response({"parsed_data": parsed_data}, status=status.HTTP_200_OK)
                else:
                    return Response(
                        {"error": response_json},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)