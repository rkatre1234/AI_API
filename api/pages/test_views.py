import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from ..serializers import ResumeParserSerializer

# Load environment variables from .env file
load_dotenv()
HF_API_KEY = os.getenv("HF_API_KEY")

class TestView(APIView):
    def post(self, request):
        serializer = ResumeParserSerializer(data=request.data)

        if serializer.is_valid():
            try:
                resume_text = serializer.validated_data.get("resume_text", "")

                # Initialize OpenAI client with Hugging Face API key
                client = OpenAI(
                    base_url="https://router.huggingface.co/together",
                    api_key=HF_API_KEY
                )

                messages = [
                    {
                        "role": "system",
                        "content": "You are a professional resume parser. Extract structured data in valid JSON format only."
                    },
                    {
                        "role": "user",
                        "content": f"Extract structured details from this resume:\n\n{resume_text}\n\n"
                                   "Return a valid JSON object with fields: name, contact, summary, experience, education, skills, certifications, projects, awards. "
                                   "Do NOT include extra text or explanations, ONLY return a valid JSON object."
                    }
                ]

                completion = client.chat.completions.create(
                    model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
                    messages=messages,
                    max_tokens=1000,
                )

                # Extract raw response text
                raw_response = completion.choices[0].message.content.strip()

                try:
                    # Attempt to parse the JSON string into a dictionary
                    parsed_resume = json.loads(raw_response)
                except json.JSONDecodeError:
                    # If the response is not valid JSON, attempt cleanup
                    raw_response = raw_response.strip("```json").strip("```")  # Remove code block markers
                    try:
                        parsed_resume = json.loads(raw_response)
                    except json.JSONDecodeError:
                        parsed_resume = {"error": "Invalid JSON format received from API", "raw_response": raw_response}

                response_data = {
                    "message": "Resume parsed successfully",
                    "parsed_resume": parsed_resume,
                }

                return Response(response_data, status=status.HTTP_200_OK)

            except Exception as e:
                return Response(
                    {"error": "Failed to process resume", "details": str(e)},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(
            {"error": "Invalid data", "details": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )
