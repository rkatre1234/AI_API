# Django Project Setup

## Prerequisites
Ensure you have the following installed:
- Python (>= 3.8)
- pip (Python package manager)
- virtualenv (for virtual environment management)
- Git

## Installation

### 1. Clone the Repository
```sh
git clone https://github.com/your-username/your-repo.git
cd your-repo
```

### 2. Create a Virtual Environment
```sh
python -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
```

### 3. Install Dependencies
```sh
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Create a `.env` file in the project root and configure necessary settings (if applicable).

### 5. Apply Migrations
```sh
python manage.py makemigrations
python manage.py migrate
```

### 6. Create a Superuser (Optional)
```sh
python manage.py createsuperuser
```
Follow the prompts to set up an admin account.

### 7. Run the Development Server
```sh
python manage.py runserver 0.0.0.0:8000
```
Access the project at `http://3.93.231.224:8000/`

## Running Tests
```sh
python manage.py test
```

## Deploying the Project
For production, consider using:
- `gunicorn` or `uwsgi` as a WSGI server
- `nginx` as a reverse proxy
- A proper database (PostgreSQL, MySQL, etc.) instead of SQLite

## Contributing
1. Fork the repository
2. Create a new branch (`git checkout -b feature-branch`)
3. Make your changes and commit (`git commit -m "Description of changes"`)
4. Push to your fork (`git push origin feature-branch`)
5. Create a Pull Request

## License
This project is licensed under the MIT License.

ps aux | grep '[p]ython'

ps aux | grep '[m]anage.py'


 /home/ec2-user/AI_API/venv/bin/python manage.py runserver 0.0.0.0:8080


nohup /home/ec2-user/AI_API/venv/bin/python manage.py runserver 0.0.0.0:8080 > server.log 2>&1 &


## Elasticsearch Setup

### Windows Installation
1. Download Elasticsearch from https://www.elastic.co/downloads/elasticsearch
2. Extract the zip file to a location (e.g., C:\elasticsearch)
3. Open PowerShell and navigate to the Elasticsearch directory:
```sh
cd C:\elasticsearch\elasticsearch-<version>
```
4. Start Elasticsearch:
```sh
.\bin\elasticsearch.bat
```

### Docker Installation (Alternative)
1. First start Elasticsearch:
```sh
docker-compose up elasticsearch -d
```

2. Create service account token for Kibana:
```sh
# Connect to Elasticsearch container
docker exec -it ai_apis-elasticsearch-1 bash

# Create service account token
bin/elasticsearch-service-tokens create elastic/kibana kibana-token
```

3. Copy the generated token and update the `ELASTICSEARCH_SERVICEACCOUNTTOKEN` in docker-compose.yml

4. Start Kibana:
```sh
docker-compose up kibana -d
```

Access Elasticsearch: http://localhost:9200
Access Kibana: http://localhost:5601

### Troubleshooting
If you encounter connection errors (e.g., "Connection refused" on port 9200):

1. Verify Elasticsearch is running:
   ```sh
   curl http://localhost:9200
   ```

2. Check Windows Services:
   - Open Services (services.msc)
   - Look for "Elasticsearch" service
   - Ensure it's running and set to "Automatic"

3. Common Solutions:
   - Ensure port 9200 is not blocked by firewall
   - Wait 30-60 seconds after starting for service to be ready
   - Check elasticsearch.yml for correct host binding
   - Verify Java is installed and JAVA_HOME is set

4. Development Quick Fix:
   ```sh
   # Kill any existing Elasticsearch processes
   taskkill /F /IM elasticsearch.bat
   # Start fresh instance
   .\bin\elasticsearch.bat
   ```

