import os
import json
import google.generativeai as genai
import requests
from dotenv import load_dotenv
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from ..serializers import ResumeParserSerializer, FileUploadSerializer
from ..responses import ApiResponse
from pathlib import Path
from docx import Document
import boto3
import fitz
import gdown

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HF_API_KEY = os.getenv("HF_API_KEY")
# Get project root from .env or fallback to script's parent directory
PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", Path(__file__).resolve().parent.parent))


# Configure Google Gemini AI client
genai.configure(api_key=GEMINI_API_KEY)

def get_absolute_path(uploaded_relative_path):
    """
    Converts a Linux-style uploaded path to a Windows-compatible absolute path.
    Does NOT use .env.
    """
    # Get the project's root dynamically (assumes script is run from the project folder)
    PROJECT_ROOT = Path.cwd()  # Uses current working directory

    # Normalize the path for the current OS
    absolute_path = (PROJECT_ROOT / Path(uploaded_relative_path.lstrip("/"))).resolve()

    # Debugging: Print paths
    print(f"PROJECT_ROOT: {PROJECT_ROOT}")
    print(f"Original Uploaded Path: {uploaded_relative_path}")
    print(f"Resolved Absolute Path: {absolute_path}")

    return str(absolute_path)

def check_file_type(file_path):
    ext = Path(file_path).suffix.lower().strip()  # Normalize case & remove spaces
    
    if ext == ".pdf":
        return ".pdf"
    elif ext in (".doc", ".docx"):
        return ".doc"
    else:
        return "Unknown file type"

def pdf_to_text(pdf_path):
    doc = fitz.open(get_absolute_path(pdf_path))
    text = "\n".join(page.get_text() for page in doc)
    return text
def doc_to_text(docx_path):
    doc = Document(get_absolute_path(docx_path))
    text = "\n".join([para.text for para in doc.paragraphs])
    print(text)
    return text

class FileUploadView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        file_serializer = FileUploadSerializer(data=request.data)
        if file_serializer.is_valid():
            file_serializer.save()
            user_data = {"file_link":file_serializer.data}

            if request.data.get('upload_type') == 'resume':
                ext = check_file_type(file_serializer.data['file'])

                if ext == ".pdf":
                    resume_text = pdf_to_text(file_serializer.data['file'])
                elif ext == ".doc" or ext == ".docx":
                    resume_text = doc_to_text(file_serializer.data['file'])
                else:
                    resume_text = "File not supported"
                
                if resume_text == "File not supported":
                    return ApiResponse.error(message="File not supported", errors="File not supported")
                else:   
                    resume_data = parse_resume_with_gemini(resume_text)
                    response = ApiResponse(message="Resume data", data=resume_data) 
                    return response.to_response()
                # resume_data ={"resume_text"}
                          
            else:
                response = ApiResponse(message="file uploaded successfully", data=user_data)           
                
            return response.to_response()
            # return Response({"file_link":file_serializer.data, "status":"true" }, status=201)
        #return Response(file_serializer.errors, status=400)
        return ApiResponse.error(message="Failed to upload", errors=str(file_serializer.errors))
        

def check_huggingface_rate_limit(api_key):
    """
    Checks the Hugging Face API rate limit and remaining requests.
    """
    API_URL = "https://api-inference.huggingface.co/models/meta-llama/Llama-3.3-70B-Instruct-Turbo"
    HEADERS = {"Authorization": f"Bearer {api_key}"}

    response = requests.get(API_URL, headers=HEADERS)

    if response.status_code == 200:
        return {
            "Rate Limit": response.headers.get("x-ratelimit-limit", "Unknown"),
            "Remaining Requests": response.headers.get("x-ratelimit-remaining", "Unknown"),
            "Resets In (seconds)": response.headers.get("x-ratelimit-reset", "Unknown")
        }
    elif response.status_code == 429:
        return {"error": "Rate limit exceeded! Please wait before making more requests."}
    else:
        return {"error": f"Failed to fetch rate limits. Status Code: {response.status_code}", "details": response.text}


def parse_resume_with_gemini(resume_text):
    """
    Uses Google Gemini Pro to parse resume text and return structured data.
    """
    messages = f"""
You are a resume parsing assistant. Given the following resume text, extract all the important details and return them in a well-structured JSON format.

The resume text:
{resume_text}

Extract and include the following:

    * Full Name: First Name, Last Name
    * Contact Number
    * Email Address
    * Location
    * Languages:
        * Language: Language name
        * Proficiency: Proficiency level (e.g., Native, Fluent, Intermediate, Beginner)
    * Summary: Professional Summary (or) Objective
    * Skills: 
        * Technical 
        * Non-Technical
    * Education: 
        * Institution: Name of institution
        * Course: Course
        * GPA: GPA (if available)
        * Location: Location
        * Year: Year
    * Work Experience:
        * Job Title: job title
        * Company: name of the company
        * Location: location
        * Dates of Employment: dates of employment
        * Responsibilities: key responsibilities and achievements
    * Certifications:
        * Name: Name of the certification
        * Issuing Organization: Issuing organization
        * Date: date
    * Projects: 
        * Title: Title of the project
        * Description: Brief description

* **Suggested Resume Category** (Based on skills and experience)
* **Recommended Job Roles** (Based on the candidate's skills and experience)

    If any detail is missing, mark it as "N/A."

Return the response in Structured clean JSON format and make sure it is free of any comments or unnecessary non-json characters.
"""


    try:
        model = genai.GenerativeModel("gemini-1.5-pro")
        response = model.generate_content(messages)

        raw_response = response.text.strip()

        # Attempt to parse JSON response
        parsed_resume = json.loads(raw_response)
        parsed_resume = json.dumps(parsed_resume, indent=4)

    except json.JSONDecodeError:
        raw_response = raw_response.strip("```json").strip("```")
        try:
            parsed_resume = json.loads(raw_response)
        except json.JSONDecodeError:
            parsed_resume = {"error": "Invalid JSON format received from API", "raw_response": raw_response}

    except Exception as e:
        return {"error": "Failed to process resume with Gemini", "details": str(e)}

    return parsed_resume


class TestView(APIView):
    """
    Existing API using Hugging Face model.
    """
    def post(self, request):
        serializer = ResumeParserSerializer(data=request.data)

        if serializer.is_valid():
            try:
                resume_text = serializer.validated_data.get("resume_text", "")

                response_data = {
                    "message": "Resume parsed successfully",
                    "usagelimit": check_huggingface_rate_limit(HF_API_KEY),
                    "parsed_resume": {"info": "This function still uses Hugging Face."},  # Placeholder
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


class GeminiView(APIView):
    """
    New API for Gemini Pro model.
    """
    def post(self, request):
        serializer = ResumeParserSerializer(data=request.data)

        if serializer.is_valid():
            try:
                resume_text = serializer.validated_data.get("resume_text", "")

                # Process resume with Gemini Pro
                parsed_resume = parse_resume_with_gemini(resume_text)

                response_data = {
                    "message": "Resume parsed successfully using Gemini Pro",
                    "parsed_resume": parsed_resume,
                }

                return Response(response_data, status=status.HTTP_200_OK)

            except Exception as e:
                return Response(
                    {"error": "Failed to process resume with Gemini", "details": str(e)},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(
            {"error": "Invalid data", "details": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )


class GoogleDriveToS3View(APIView):
    """
    API to download a video from a public Google Drive link and upload it to an S3 bucket.
    """
    def post(self, request):
        try:
            # Extract Google Drive file link from the payload
            google_drive_file_link = request.data.get("google_drive_file_link")
            if not google_drive_file_link:
                return Response({"error": "Google Drive file link is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Validate the Google Drive link
            if "drive.google.com" not in google_drive_file_link:
                return Response({"error": "Invalid Google Drive link"}, status=status.HTTP_400_BAD_REQUEST)

            # Convert the public Google Drive link to a direct download link
            file_id = google_drive_file_link.split("/d/")[1].split("/")[0]
            download_url = f"https://drive.google.com/uc?id={file_id}"
            print(f"Download URL: {download_url}")  # Debugging

            # Use a valid directory for temporary file storage
            temp_dir = os.getenv("TEMP_DIR", ".")  # Default to current directory if TEMP_DIR is not set
            local_file_path = os.path.join(temp_dir, f"{file_id}.mp4")
            print(f"Temporary file path: {local_file_path}")  # Debugging

            # Download the file using gdown
            gdown.download(download_url, local_file_path, quiet=False)

            # Upload the file to S3 with progress tracking
            aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
            aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
            bucket_name = os.getenv("AWS_S3_BUCKET_NAME")
            region_name = os.getenv("AWS_REGION", "us-east-1")
            s3_key = f"videos/{file_id}.mp4"

            def upload_progress(bytes_transferred):
                print(f"Upload progress: {bytes_transferred} bytes transferred")  # Progress tracking

            s3_client = boto3.client(
                "s3",
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                region_name=region_name,
            )
            s3_client.upload_file(
                local_file_path, bucket_name, s3_key,
                Callback=lambda bytes_transferred: upload_progress(bytes_transferred)
            )
            print(f"File uploaded to S3: {s3_key}")  # Debugging

            # Delete the local file after successful upload
            if os.path.exists(local_file_path):
                os.remove(local_file_path)
                print(f"Temporary file deleted: {local_file_path}")  # Debugging

            # Generate the S3 URL
            s3_url = f"https://{bucket_name}.s3.{region_name}.amazonaws.com/{s3_key}"
            print(f"S3 URL: {s3_url}")  # Debugging

            # Return success response
            return Response({
                "message": "File successfully transferred from Google Drive to S3",
                "s3_url": s3_url
            }, status=status.HTTP_200_OK)

        except Exception as e:
            print(f"Error: {str(e)}")  # Debugging
            return Response({
                "error": "Failed to transfer file",
                "details": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
