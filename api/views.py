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
                        "prompt":  f"""
You are an AI specialized in **resume parsing**. Extract structured details from the given resume text and return **valid JSON output**.

### **Resume Text:**
{resume_text}

### **Instructions:**
1. **Extract and format** the following details:
   - `name` → Full name of the candidate.
   - `contact` → Includes `email` (list) and `phone_numbers` (list).
   - `skills` → A list of skills (tech & soft).
   - `experience` → A structured list with `company`, `position`, `start_year`, `end_year`, and `years_of_experience`.
   - `education` → Includes `degree`, `institution`, and `year_of_graduation`.
   - `certifications` → If available, include `name`, `issued_by`, and `year`.
   - `projects` → If available, include `title`, `description`, `technologies`, and `year`.

2. **Output must be JSON**, properly formatted and free of errors.

3. **Example JSON Output:**
```json
{{
    "name": "John Doe",
    "contact": {{
        "email": ["john.doe@example.com"],
        "phone_numbers": ["+1-555-123-4567"]
    }},
    "skills": ["Python", "Machine Learning", "Leadership"],
    "experience": [
        {{
            "company": "Google",
            "position": "Software Engineer",
            "start_year": 2018,
            "end_year": 2023,
            "years_of_experience": 5
        }},
        {{
            "company": "Amazon",
            "position": "Senior Developer",
            "start_year": 2015,
            "end_year": 2018,
            "years_of_experience": 3
        }}
    ],
    "education": [
        {{
            "degree": "B.Sc. in Computer Science",
            "institution": "MIT",
            "year_of_graduation": 2015
        }}
    ],
    "certifications": [
        {{
            "name": "AWS Certified Solutions Architect",
            "issued_by": "Amazon Web Services",
            "year": 2021
        }}
    ],
    "projects": [
        {{
            "title": "AI Chatbot",
            "description": "Developed an AI chatbot using NLP.",
            "technologies": ["Python", "TensorFlow"],
            "year": 2022
        }}
    ]
}}

""",
                        "stream": False  # Disable streaming to ensure JSON response
                    },
                    timeout=3000
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