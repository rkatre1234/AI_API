from django.core.management.base import BaseCommand
from elasticsearch import Elasticsearch, ConnectionError, TransportError, ElasticsearchWarning
from django.conf import settings
import os
import json
import logging
import warnings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('elasticsearch')

# Filter ElasticsearchWarning about system indices
warnings.filterwarnings('ignore', category=ElasticsearchWarning, message='this request accesses system indices:*')

class Command(BaseCommand):
    help = 'Check Elasticsearch connection and configuration'

    def handle(self, *args, **options):
        self.stdout.write('Testing Elasticsearch connection...')
        
        # Get ES config from environment
        es_host = os.getenv("ELASTICSEARCH_HOST", "127.0.0.1")
        es_port = int(os.getenv("ELASTICSEARCH_PORT", 9200))
        es_user = os.getenv("ELASTICSEARCH_USER")
        es_pass = os.getenv("ELASTICSEARCH_PASSWORD")
        es_use_ssl = os.getenv("ELASTICSEARCH_USE_SSL", "false").lower() == "true"
        
        config = {
            'hosts': [f"{'https' if es_use_ssl else 'http'}://{es_host}:{es_port}"],
            'basic_auth': (es_user, es_pass) if es_user and es_pass else None,
            'verify_certs': False,
            'request_timeout': 30,
            'retry_on_timeout': True,
            'max_retries': 3,
            'api_key': None  # Explicitly set to None for ES 8.x
        }

        try:
            # Create client with ES 8.x settings
            es = Elasticsearch(
                **config,
                headers={'Content-Type': 'application/json'}
            )
            
            # Test connection
            self.stdout.write(f"Trying to connect to {config['hosts'][0]}...")
            
            if es.ping():
                self.stdout.write(self.style.SUCCESS('✓ Successfully connected to Elasticsearch'))
                
                # Get cluster info
                info = es.info()
                self.stdout.write(f"Cluster Name: {info['cluster_name']}")
                self.stdout.write(f"Elasticsearch Version: {info['version']['number']}")
                
                # Check cluster health
                health = es.cluster.health()
                self.stdout.write(f"Cluster Status: {health['status']}")
                self.stdout.write(f"Number of nodes: {health['number_of_nodes']}")
                
                # List indices with better formatting
                indices = es.indices.get_alias()
                self.stdout.write("\nIndices:")
                
                # Separate system and regular indices
                system_indices = [idx for idx in indices if idx.startswith('.')]
                regular_indices = [idx for idx in indices if not idx.startswith('.')]
                
                if regular_indices:
                    self.stdout.write("\nRegular Indices:")
                    for index in sorted(regular_indices):
                        self.stdout.write(f"  - {index}")
                        
                if system_indices and not options.get('hide_system', False):
                    self.stdout.write("\nSystem Indices:")
                    for index in sorted(system_indices):
                        self.stdout.write(f"  - {index}")

            else:
                self.stdout.write(self.style.WARNING("Ping failed, checking connection details..."))
                try:
                    info = es.info()
                    self.stdout.write(self.style.SUCCESS("Connection successful despite ping failure"))
                    self.stdout.write(f"Cluster info: {json.dumps(info, indent=2)}")
                except Exception as detail_e:
                    self.stdout.write(self.style.ERROR(f"Connection check failed: {str(detail_e)}"))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Connection failed: {str(e)}'))
            logger.error(f"Full error details: {str(e)}", exc_info=True)

    def add_arguments(self, parser):
        parser.add_argument(
            '--hide-system',
            action='store_true',
            help='Hide system indices in the output'
        )
