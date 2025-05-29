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
from docx2pdf import convert
import pytesseract
from PIL import Image
import io
from datetime import datetime
import platform
import subprocess

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
    text = []
    
    for page in doc:
        # Get text from regular text content
        text.append(page.get_text())
        
        # Extract text from images
        images = page.get_images()
        for img_index, img in enumerate(images):
            try:
                # Get image data
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                
                # Convert to PIL Image
                image = Image.open(io.BytesIO(image_bytes))
                
                # Use OCR to extract text from image
                img_text = pytesseract.image_to_string(image)
                if img_text.strip():  # Only add if text was found
                    text.append(img_text)
                    
            except Exception as e:
                print(f"Error processing image {img_index}: {str(e)}")
                continue
    
    return "\n".join(text)

def convert_to_pdf_linux(input_path, output_path):
    """Convert document to PDF using LibreOffice on Linux"""
    try:
        # Convert using LibreOffice
        cmd = ['soffice', '--headless', '--convert-to', 'pdf', '--outdir', 
               os.path.dirname(output_path), input_path]
        process = subprocess.run(cmd, capture_output=True, text=True)
        
        if process.returncode != 0:
            raise Exception(f"LibreOffice conversion failed: {process.stderr}")
            
        return True
    except Exception as e:
        print(f"LibreOffice conversion error: {str(e)}")
        return False

def doc_to_text(docx_path):
    # Get absolute paths
    abs_path = get_absolute_path(docx_path)
    file_ext = Path(abs_path).suffix.lower()
    pdf_path = abs_path.rsplit('.', 1)[0] + '.pdf'
    
    try:
        # Convert DOC/DOCX to PDF
        if file_ext in ['.doc', '.docx']:
            print(f"Starting conversion of {file_ext} to PDF...")
            
            # Use appropriate converter based on OS
            if platform.system() == 'Windows':
                convert(abs_path, pdf_path)
            else:
                if not convert_to_pdf_linux(abs_path, pdf_path):
                    raise Exception("PDF conversion failed on Linux")
                
            print("Conversion completed successfully")
        else:
            raise ValueError(f"Unsupported file extension: {file_ext}")
        
        # Use existing pdf_to_text function to extract text
        text = pdf_to_text(pdf_path)
        
        # Cleanup both temporary PDF and original DOC/DOCX
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
            print(f"Deleted temporary PDF: {pdf_path}")
            
        if os.path.exists(abs_path):
            os.remove(abs_path)
            print(f"Deleted original document: {abs_path}")
            
        return text
    except Exception as e:
        error_msg = str(e)
        if "not implemented for linux" in error_msg.lower():
            return {
                "status": "error",
                "code": "CONVERSION_NOT_AVAILABLE",
                "message": "Document conversion not available",
                "details": "LibreOffice is required on Linux systems",
                "path": abs_path
            }
        elif "file not found" in error_msg.lower():
            return {
                "status": "error",
                "code": "FILE_NOT_FOUND",
                "message": "Document not found",
                "details": f"File not found at path: {abs_path}",
                "path": abs_path
            }
        elif "permission denied" in error_msg.lower():
            return {
                "status": "error",
                "code": "PERMISSION_DENIED",
                "message": "Permission denied",
                "details": "Unable to access document due to permission restrictions",
                "path": abs_path
            }
        elif "memory" in error_msg.lower():
            return {
                "status": "error",
                "code": "OUT_OF_MEMORY",
                "message": "System out of memory",
                "details": "Insufficient memory to process document",
                "path": abs_path
            }
        else:
            return {
                "status": "error",
                "code": "PROCESSING_ERROR",
                "message": "Document processing failed",
                "details": error_msg,
                "path": abs_path
            }

class FileUploadView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        file_serializer = FileUploadSerializer(data=request.data)
        if file_serializer.is_valid():
            file_serializer.save()
            user_data = {"file_link":file_serializer.data}

            if request.data.get('upload_type') == 'resume':
                ext = check_file_type(file_serializer.data['file'])

                try:
                    if ext == ".pdf":
                        resume_text = pdf_to_text(file_serializer.data['file'])
                    elif ext in (".doc", ".docx"):
                        result = doc_to_text(file_serializer.data['file'])
                        # Check if result is an error dictionary
                        if isinstance(result, dict) and result.get('status') == 'error':
                            return ApiResponse.error(
                                message=result.get('message', 'Error processing file'),
                                errors=result.get('details', 'Unknown error')
                            )
                        resume_text = result
                    else:
                        resume_text = "File not supported"
                except Exception as e:
                    return ApiResponse.error(message="Error processing file", errors=str(e))
                
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
    # Check for blank or empty resume text
    if not resume_text or resume_text.strip() == "":
        return {
            "error": "Empty resume",
            "message": "The resume text is empty. Please provide resume content to parse."
        }

    json_template = '''{
    "FullName": {
        "FirstName": "",
        "LastName": ""
    },
    "ContactNumber": {
        "countryCode": "",
        "number": ""
    },
    "EmailAddress": "",
    "DOB": "",
    "PreferredJobLocation": {
        "City": "",
        "State": "",
        "Country": "",
        "ZipCode": "",
        "PhoneNumber": {
            "CountryCode": "",
            "Number": ""
        },
        "Address": ""
    },
    "Nationality": "",
    "Languages": [
        {
            "Language": "",
            "Proficiency": ""
        }
    ],
    "Summary": "",
    "Skills": {
        "Technical": [],
        "NonTechnical": []
    },
    "Education": [
        {
            "Institution": "",
            "Course": "",
            "GPA": "",
            "Location": "",
            "Year": "",
            "Major": ""
        }
    ],
    "WorkExperience": [
        {
            "JobTitle": "",
            "Company": "",
            "Location": "",
            "DatesOfEmployment": {
                "StartDate": {
                    "Day": "",
                    "Month": "",
                    "Year": ""
                },
                "EndDate": {
                    "Day": "",
                    "Month": "",
                    "Year": ""
                }
            },
            "Responsibilities": [],
            "Description": [],
            "ProjectsUndertaken": [],
            "TechnologiesUsed": []
        }
    ],
    "Certifications": [
        {
            "Name": "",
            "IssuingOrganization": "",
            "Date": "dd/mm/yyyy"
        }
    ],
    "Projects": [
        {
            "Title": "",
            "Description": "",
            "TechnologiesUsed": [],
            "Role": "",
            "Duration": "",
            "Responsibilities": []
        }
    ],
    "TotalExperienceInYears": "",
    "ExpectedRateOrSalary": {
        "Yearly": "",
        "Monthly": "",
        "Daily": "",
        "Hourly": ""
    },
    "AvailableToJoinOrLastWorkingDay": "dd/mm/yyyy",
    "AvailableFor": {
        "Contract": "",
        "FTE": "",
        "ContractPlusFTE": "",
        "PartTime": ""
    },
    "CandidatePersonalDetails": {
        "LinkedInProfileURL": "",
        "GitHubProfileURL": "",
        "PortfolioURL": "",
        "WebsiteURL": "",
        "OtherURLs": "",
        "TwitterURL": "",
        "FacebookURL": "",
        "InstagramURL": "",
        "DOB": "",
        "Gender": "",
        "PinCodeOrZipCode": "",
        "Address": "",
        "City": "",
        "State": "",
        "Country": ""
    },
    "ProfessionalSummary": "",
    "CurrentDesignation": "",
    "References": [
        {
            "ReferenceName": "",
            "ContactInformation": ""
        }
    ],
    "SuggestedResumeCategory": "",
    "RecommendedJobRoles": []
}'''

    # Add instructions for DOB and date fields
    # - If DOB is not available in the resume, do not include the "DOB" key at all in the output.
    # - For any date fields, if the date does not exist in the resume, use "0000-00-00 00:00:00" as the value.
    # - For DatesOfEmployment in WorkExperience, parse StartDate and EndDate as objects with "Day", "Month", and "Year" keys. If only month and year are available, leave "Day" as empty string.

    # Ensure log directory exists
    log_dir = PROJECT_ROOT / "media" / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"gemini_prompt_{datetime.now().strftime('%Y-%m-%d')}.log"

    # Prepare the prompt
    messages = f"""
        You are a resume parsing assistant. Given the following resume text, extract all the important details and return them in a well-structured JSON format.
        For all dates, use the format dd/mm/yyyy (e.g., 25/12/2023). if not exist make empty string.
        For the "DOB" (Date of Birth) field, if it is not available in the resume, "DOB" key should be empty string in the output JSON.
        For DatesOfEmployment in WorkExperience, parse StartDate and EndDate as objects with "Day", "Month", and "Year" keys. If only month and year are available, leave "Day" as empty string.

        The resume text:
        {resume_text}

        Extract and include the following (if data is missing, mark it as " "), except for DOB as described above:

        {json_template}
        """

    # Log the prompt to the log file
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n--- {datetime.now().isoformat()} ---\n")
        f.write(messages)
        f.write("\n--- END ---\n")

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
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
    API to download files (video and image) from Google Drive or direct links and upload them to an S3 bucket.
    """
    def post(self, request):
        try:
            # Extract file keys (URLs) and names from the payload
            video_key = request.data.get("video_key")
            video_name = request.data.get("video_name")
            image_key = request.data.get("image_key")
            image_name = request.data.get("image_name")

            print(f"Received payload: {request.data}")  # Debugging

            if not video_key or not video_name or not image_key or not image_name:
                return Response({"error": "All file keys and names are required"}, status=status.HTTP_400_BAD_REQUEST)

            def process_file(file_key, file_name):
                try:
                    # Decide if it's a Google Drive link or a direct URL
                    if "drive.google.com" in file_key:
                        # Extract file ID and convert to direct link
                        file_id = file_key.split("/d/")[1].split("/")[0]
                        download_url = f"https://drive.google.com/uc?id={file_id}"
                        is_google_drive = True
                    else:
                        download_url = file_key
                        is_google_drive = False

                    uploads_dir = os.path.join(PROJECT_ROOT, "uploads")
                    os.makedirs(uploads_dir, exist_ok=True)
                    local_file_path = os.path.join(uploads_dir, file_name)
                    print(f"Download URL: {download_url}")
                    print(f"Local file path: {local_file_path}")

                    if is_google_drive:
                        gdown.download(download_url, local_file_path, quiet=False)
                    else:
                        response = requests.get(download_url, stream=True)
                        response.raise_for_status()
                        with open(local_file_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                f.write(chunk)

                    # Upload to S3
                    aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
                    aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
                    bucket_name = os.getenv("AWS_S3_BUCKET_NAME")
                    region_name = os.getenv("AWS_REGION", "us-east-1")
                    s3_key = f"uploads/{file_name}"

                    def upload_progress(bytes_transferred):
                        print(f"Upload progress: {bytes_transferred} bytes transferred")

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
                    print(f"File uploaded to S3: {s3_key}")

                    # Clean up
                    if os.path.exists(local_file_path):
                        os.remove(local_file_path)
                        print(f"Deleted local file: {local_file_path}")

                    return f"https://{bucket_name}.s3.{region_name}.amazonaws.com/{s3_key}"

                except Exception as e:
                    print(f"Error processing file {file_name}: {str(e)}")
                    raise

            video_s3_url = process_file(video_key, video_name)
            image_s3_url = process_file(image_key, image_name)

            return Response({
                "message": "Files successfully uploaded to S3",
                "video_s3_url": video_s3_url,
                "image_s3_url": image_s3_url,
                "file_key": video_name,
                "reference_image": image_name
            }, status=status.HTTP_200_OK)

        except PermissionError as e:
            return Response({"error": "Permission error", "details": str(e)}, status=status.HTTP_403_FORBIDDEN)

        except Exception as e:
            return Response({"error": "Failed to upload files", "details": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

