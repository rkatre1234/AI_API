import os
import json
import time
import google.generativeai as genai
import requests
from dotenv import load_dotenv
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from ..serializers import ResumeParserSerializer, FileUploadSerializer, JobSearchSerializer
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
from elasticsearch import Elasticsearch, ConnectionError, ConnectionTimeout
import pythoncom  # Add this import at the top
import logging
import grpc

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HF_API_KEY = os.getenv("HF_API_KEY")

# Elasticsearch Configuration
ES_HOST = os.getenv("ELASTICSEARCH_HOST", "127.0.0.1")
ES_PORT = int(os.getenv("ELASTICSEARCH_PORT", 9200))
ES_USER = os.getenv("ELASTICSEARCH_USER")
ES_PASS = os.getenv("ELASTICSEARCH_PASSWORD")
ES_USE_SSL = os.getenv("ELASTICSEARCH_USE_SSL", "false").lower() == "true"
ES_VERIFY_CERTS = os.getenv("ELASTICSEARCH_VERIFY_CERTS", "false").lower() == "true"

# Update ES configuration constants
ES_INDEX_NAME = "parsed_resumes"
ES_TIMEOUT = int(os.getenv("ELASTICSEARCH_TIMEOUT", 30))
ES_MAX_RETRIES = int(os.getenv("ELASTICSEARCH_MAX_RETRIES", 3))
ES_RETRY_DELAY = int(os.getenv("ELASTICSEARCH_RETRY_DELAY", 5))

ES_MAPPING = {
    "mappings": {
        "properties": {
            "FullName": {
                "properties": {
                    "FirstName": {"type": "text"},
                    "LastName": {"type": "text"}
                }
            },
            "Skills": {
                "properties": {
                    "Technical": {"type": "keyword"},
                    "NonTechnical": {"type": "keyword"}
                }
            },
            "TotalExperienceInYears": {"type": "float"},
            "CurrentDesignation": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "WorkExperience": {
                "properties": {
                    "JobTitle": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "Company": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "Location": {"type": "text"}
                }
            },
            "PreferredJobLocation": {
                "properties": {
                    "City": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "State": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "Country": {"type": "text", "fields": {"keyword": {"type": "keyword"}}}
                }
            }
        }
    },
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0
    }
}

# Get project root from .env or fallback to script's parent directory
PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", Path(__file__).resolve().parent.parent))
MEDIA_DIR = PROJECT_ROOT / "media"
UPLOADS_DIR = MEDIA_DIR / "uploads"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_elasticsearch_status():
    """Check if Elasticsearch is installed and running"""
    try:
        es = get_elasticsearch_client()
        if es is None:
            return {
                "installed": False,
                "status": "error",
                "message": "Failed to initialize Elasticsearch client"
            }
        
        info = es.info()
        return {
            "installed": True,
            "status": "ok",
            "version": info.get("version", {}).get("number", "unknown"),
            "cluster_name": info.get("cluster_name", "unknown"),
            "message": "Elasticsearch is running"
        }
    except Exception as e:
        return {
            "installed": False,
            "status": "error",
            "message": f"Elasticsearch error: {str(e)}",
            "help": "Please ensure Elasticsearch is installed and running"
        }

def get_elasticsearch_client(max_retries=ES_MAX_RETRIES, retry_delay=ES_RETRY_DELAY):
    """Get configured Elasticsearch client with retry logic and connection pooling"""
    for attempt in range(max_retries):
        try:
            config = {
                'hosts': [f"{'https' if ES_USE_SSL else 'http'}://{ES_HOST}:{ES_PORT}"],
                'basic_auth': (ES_USER, ES_PASS) if ES_USER and ES_PASS else None,
                'verify_certs': ES_VERIFY_CERTS,
                'timeout': ES_TIMEOUT,
                'max_retries': 3,
                'retry_on_timeout': True
            }

            es = Elasticsearch(**config)
            
            # Test connection with retry
            if es.ping():
                logger.info(f"Successfully connected to Elasticsearch at {ES_HOST}:{ES_PORT}")
                
                # Create index if doesn't exist
                if not es.indices.exists(index=ES_INDEX_NAME):
                    es.indices.create(index=ES_INDEX_NAME, mappings=ES_MAPPING["mappings"])
                    logger.info(f"Created index {ES_INDEX_NAME} with mappings")
                
                return es
            
        except Exception as e:
            logger.error(f"Elasticsearch connection attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            continue
    
    logger.error("Failed to connect to Elasticsearch after all retries")
    return None

# Configure Google Gemini AI client
genai.configure(api_key=GEMINI_API_KEY)

def get_absolute_path(uploaded_relative_path):
    """Converts uploaded path to absolute path using PROJECT_ROOT"""
    # Normalize path separators and remove any duplicate media/uploads segments
    clean_path = str(uploaded_relative_path).replace('\\', '/')
    clean_path = clean_path.replace('media/uploads/media/uploads/', 'media/uploads/')
    clean_path = os.path.basename(clean_path)  # Just take the filename
    
    # Ensure upload directory exists
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Create platform-independent path
    abs_path = UPLOADS_DIR / clean_path
    return str(abs_path)

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
    
    # Check tesseract before processing images
    tesseract_status = check_tesseract_installation()
    if not tesseract_status["installed"]:
        logger.warning(f"Tesseract not available - {tesseract_status['help']}")
    
    for page in doc:
        # Get text from regular text content
        text.append(page.get_text())
        
        # Extract text from images only if tesseract is available
        if tesseract_status["installed"]:
            images = page.get_images()
            for img_index, img in enumerate(images):
                try:
                    xref = img[0]
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    
                    image = Image.open(io.BytesIO(image_bytes))
                    img_text = pytesseract.image_to_string(image)
                    
                    if img_text.strip():
                        text.append(img_text)
                        
                except Exception as e:
                    logger.warning(f"Error processing image {img_index}: {str(e)}")
                    continue
        
    return "\n".join(text)

def check_libreoffice_installation():
    """Check LibreOffice installation details on Linux"""
    checks = [
        "which soffice",
        "whereis soffice",
        "soffice --version",
        "ls -l /usr/bin/soffice",
        "ls -l /usr/lib/libreoffice",
        "ls -l /opt/libreoffice"
    ]
    
    results = {}
    for cmd in checks:
        try:
            output = subprocess.run(cmd.split(), capture_output=True, text=True)
            results[cmd] = {
                'returncode': output.returncode,
                'stdout': output.stdout.strip(),
                'stderr': output.stderr.strip()
            }
        except Exception as e:
            results[cmd] = {'error': str(e)}
    
    return results

def convert_to_pdf_linux(input_path, output_path):
    """Convert document to PDF using LibreOffice"""
    try:
        # Use platform-independent paths
        input_filename = os.path.basename(input_path)
        clean_input_path = str(UPLOADS_DIR / input_filename)
        
        logger.info(f"Clean input path: {clean_input_path}")
        logger.info(f"Output dir: {UPLOADS_DIR}")
        
        cmd = [
            'libreoffice',
            '--headless',
            '--convert-to', 'pdf',
            '--outdir', str(UPLOADS_DIR),
            clean_input_path
        ]
        
        logger.info(f"Executing command: {' '.join(cmd)}")
        
        process = subprocess.run(cmd, capture_output=True, text=True)
        logger.info(f"Command output: {process.stdout}")
        logger.error(f"Command errors: {process.stderr}")
        
        if process.returncode != 0:
            logger.error(f"Conversion failed with return code: {process.returncode}")
            return False
            
        # Verify output file exists    
        if not os.path.exists(output_path):
            logger.error(f"Output PDF not found at: {output_path}")
            return False
            
        logger.info("PDF conversion completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"LibreOffice conversion error: {str(e)}")
        return False

def doc_to_text(docx_path):
    # Initialize COM for the current thread if on Windows
    if platform.system() == 'Windows':
        pythoncom.CoInitialize()
    
    try:
        # Get absolute paths with fixed base dir
        abs_path = get_absolute_path(docx_path)
        file_ext = Path(abs_path).suffix.lower()
        output_filename = os.path.basename(abs_path).rsplit('.', 1)[0] + '.pdf'
        pdf_path = os.path.join(os.path.dirname(abs_path), output_filename)
        
        # Convert DOC/DOCX to PDF
        if file_ext in ['.doc', '.docx']:
            logger.info(f"Starting conversion of {file_ext} to PDF...")
            
            # Use appropriate converter based on OS
            if platform.system() == 'Windows':
                try:
                    convert(abs_path, pdf_path)
                except Exception as e:
                    logger.error(f"Windows conversion error: {str(e)}")
                    return ApiResponse.error(
                        message="Document conversion failed",
                        errors=f"Windows conversion error: {str(e)}"
                    ).to_dict()
            else:
                if not convert_to_pdf_linux(abs_path, pdf_path):
                    return ApiResponse.error(
                        message="Document conversion failed",
                        errors="LibreOffice conversion failed on Linux system"
                    ).to_dict()
            
            logger.info("Conversion completed successfully")
        else:
            raise ValueError(f"Unsupported file extension: {file_ext}")
        
        # Use existing pdf_to_text function to extract text
        text = pdf_to_text(pdf_path)
        
        # Cleanup both temporary PDF and original DOC/DOCX
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
            logger.info(f"Deleted temporary PDF: {pdf_path}")
            
        if os.path.exists(abs_path):
            os.remove(abs_path)
            logger.info(f"Deleted original document: {abs_path}")
            
        return text
    except Exception as e:
        error_msg = str(e)
        return {
            "status": "error",
            "message": "Document processing failed",
            "data": None,
            "errors": error_msg
        }
    finally:
        # Uninitialize COM if on Windows
        if platform.system() == 'Windows':
            pythoncom.CoUninitialize()

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
                        if isinstance(result, dict) and 'status' in result:
                            return Response(result, status=status.HTTP_400_BAD_REQUEST)
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


def store_parsed_resume_to_elasticsearch(parsed_resume, index_name="parsed_resumes"):
    """
    Stores the parsed resume data into Elasticsearch.
    """
    # Use global ES client
    es = get_elasticsearch_client()

    # If parsed_resume is a JSON string, convert to dict
    if isinstance(parsed_resume, str):
        try:
            parsed_resume = json.loads(parsed_resume)
        except Exception:
            return {"error": "Failed to parse resume JSON for Elasticsearch"}

    # Index the document
    try:
        resp = es.index(index=index_name, document=parsed_resume)
        return {"result": "success", "es_id": resp.get("_id")}
    except Exception as e:
        return {"error": "Failed to store in Elasticsearch", "details": str(e)}


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
                    "Day": "00",
                    "Month": "00",
                    "Year": "0000"
                },
                "EndDate": {
                    "Day": "00",
                    "Month": "00",
                    "Year": "0000"
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
        parsed_resume_str = json.dumps(parsed_resume, indent=4)

    except json.JSONDecodeError:
        raw_response = raw_response.strip("```json").strip("```")
        try:
            parsed_resume = json.loads(raw_response)
            parsed_resume_str = json.dumps(parsed_resume, indent=4)
        except json.JSONDecodeError:
            parsed_resume = {"error": "Invalid JSON format received from API", "raw_response": raw_response}
            parsed_resume_str = parsed_resume

    except Exception as e:
        return {"error": "Failed to process resume with Gemini", "details": str(e)}

    # Store to Elasticsearch
    es_result = store_parsed_resume_to_elasticsearch(parsed_resume)
    if "error" in es_result:
        # Optionally, you can log this error
        parsed_resume["elasticsearch_error"] = es_result
    else:
        parsed_resume["elasticsearch_id"] = es_result.get("es_id")

    return parsed_resume_str


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


class ResumeMatchingView(APIView):
    """API endpoint to find matching resumes for a job"""
    
    def post(self, request):
        serializer = JobSearchSerializer(data=request.data)
        
        if not serializer.is_valid():
            return ApiResponse.error(
                message="Invalid job search criteria",
                errors=serializer.errors
            ).to_response()

        try:
            matches = search_matching_resumes(serializer.validated_data)
            
            if "error" in matches:
                return ApiResponse.error(
                    message="Failed to search resumes",
                    errors=matches["details"]
                ).to_response()

            return ApiResponse(
                message="Successfully found matching resumes",
                data=matches
            ).to_response()

        except Exception as e:
            return ApiResponse.error(
                message="Error processing request",
                errors=str(e)
            ).to_response()


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

            logger.info(f"Received payload: {request.data}")  # Debugging

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
                    logger.info(f"Download URL: {download_url}")
                    logger.info(f"Local file path: {local_file_path}")

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
                        logger.info(f"Upload progress: {bytes_transferred} bytes transferred")

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
                    logger.info(f"File uploaded to S3: {s3_key}")

                    # Clean up
                    if os.path.exists(local_file_path):
                        os.remove(local_file_path)
                        logger.info(f"Deleted local file: {local_file_path}")

                    return f"https://{bucket_name}.s3.{region_name}.amazonaws.com/{s3_key}"

                except Exception as e:
                    logger.error(f"Error processing file {file_name}: {str(e)}")
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


def search_matching_resumes(job_details, index_name="parsed_resumes"):
    """Search for matching resumes based on job details"""
    try:
        # Use global ES client
        es = get_elasticsearch_client()

        # Build the search query
        must_clauses = []
        should_clauses = []

        # Match job title against multiple fields
        if job_title := job_details.get('job_title'):
            should_clauses.append({
                "multi_match": {
                    "query": job_title,
                    "fields": [
                        "CurrentDesignation^3",
                        "WorkExperience.JobTitle^2",
                        "RecommendedJobRoles^1.5",
                        "ProfessionalSummary"
                    ],
                    "type": "phrase_prefix",
                    "boost": 2.0
                }
            })

        # Match required skills
        if skills := job_details.get('skills', []):
            must_clauses.append({
                "terms_set": {
                    "Skills.Technical": {
                        "terms": skills,
                        "minimum_should_match_script": {
                            "source": f"Math.min(params.num_terms, {len(skills)-1})"
                        }
                    }
                }
            })

        # Match experience range
        if experience := job_details.get('experience'):
            must_clauses.append({
                "range": {
                    "TotalExperienceInYears": {
                        "gte": max(0, float(experience) - 2),  # 2 years flexibility
                        "lte": float(experience) + 2
                    }
                }
            })

        # Match location preferences
        if location := job_details.get('location'):
            should_clauses.append({
                "multi_match": {
                    "query": location,
                    "fields": [
                        "PreferredJobLocation.City^2",
                        "PreferredJobLocation.State^1.5",
                        "PreferredJobLocation.Country"
                    ],
                    "fuzziness": "AUTO"
                }
            })

        # Match employment type
        if emp_type := job_details.get('employment_type'):
            should_clauses.append({
                "match": {
                    "AvailableFor": emp_type
                }
            })

        # Combine all search criteria
        query = {
            "bool": {
                "must": must_clauses,
                "should": should_clauses,
                "minimum_should_match": 1 if should_clauses else 0
            }
        }

        # Execute search
        response = es.search(
            index=index_name,
            body={
                "query": query,
                "_source": {
                    "excludes": ["References", "ContactNumber", "DOB"]
                },
                "size": 10,
                "sort": [
                    {"_score": "desc"},
                    {"TotalExperienceInYears": "desc"}
                ],
                "highlight": {
                    "fields": {
                        "Skills.Technical": {},
                        "WorkExperience.JobTitle": {},
                        "ProfessionalSummary": {}
                    }
                }
            }
        )

        # Process results
        hits = response['hits']['hits']
        results = []
        max_score = float(response['hits']['max_score']) if hits else 1.0

        for hit in hits:
            match_score = (hit['_score'] / max_score) * 100
            result = {
                "resume_id": hit['_id'],
                "match_score": round(match_score, 2),
                "highlights": hit.get('highlight', {}),
                "data": {
                    "name": hit['_source'].get('FullName', {}),
                    "experience": hit['_source'].get('TotalExperienceInYears', ''),
                    "current_role": hit['_source'].get('CurrentDesignation', ''),
                    "skills": hit['_source'].get('Skills', {}).get('Technical', []),
                    "location": hit['_source'].get('PreferredJobLocation', {}),
                    "education": hit['_source'].get('Education', [])
                }
            }
            results.append(result)

        return {
            "total_matches": response['hits']['total']['value'],
            "results": results,
            "search_metadata": {
                "max_score": response['hits']['max_score'],
                "took_ms": response['took']
            }
        }

    except Exception as e:
        return {
            "error": "Failed to search resumes",
            "details": str(e)
        }

def check_tesseract_installation():
    """Check if tesseract is installed and configured"""
    try:
        # Test tesseract version
        version = pytesseract.get_tesseract_version()
        return {
            "installed": True,
            "version": str(version),
            "status": "ok"
        }
    except Exception as e:
        return {
            "installed": False,
            "error": str(e),
            "status": "error",
            "help": "Please install tesseract-ocr. On Linux: 'sudo apt-get install tesseract-ocr', on Windows download from https://github.com/UB-Mannheim/tesseract/wiki"
        }

