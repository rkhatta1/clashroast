import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'postgresql://cruser:crpassword@localhost:5433/clash_royale_db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Celery
    CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6380/0')
    CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6380/0')
    
    # Google Cloud / Vertex AI
    GCP_PROJECT_ID = os.getenv('GCP_PROJECT_ID')
    GCP_LOCATION = os.getenv('GCP_LOCATION', 'us-central1')
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    
    # Video Processing
    VIDEOS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'videos')
    FRAMES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frames')
    FRAMES_PER_SECOND = 1
    FRAMES_PER_BATCH = 5
    
    # Gemini Models
    GEMINI_FLASH_MODEL = 'gemini-3-flash-preview'
    GEMINI_PRO_MODEL = 'gemini-3-pro-preview'
