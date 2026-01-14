import os
from dotenv import load_dotenv

load_dotenv()

# Base directory for the application
BASE_DIR = os.path.dirname(os.path.dirname(__file__))


class Config:
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')

    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'postgresql://cruser:crpassword@localhost:5433/clash_royale_db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Celery (for local development)
    CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6380/0')
    CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6380/0')

    # Google Cloud / Vertex AI
    GCP_PROJECT_ID = os.getenv('GCP_PROJECT_ID')
    GCP_LOCATION = os.getenv('GCP_LOCATION', 'us-central1')
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME', 'clash-roast-videos')
    GCS_UPLOAD_PREFIX = 'uploads/'
    GCS_OUTPUT_PREFIX = 'outputs/'
    GCS_THUMBNAIL_PREFIX = 'thumbnails/'

    # Frontend
    FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:3000')
    MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB

    # Video Processing Directories
    VIDEOS_DIR = os.path.join(BASE_DIR, 'videos')
    FRAMES_DIR = os.path.join(BASE_DIR, 'frames')
    AUDIO_DIR = os.path.join(BASE_DIR, 'audio')
    OUTPUT_DIR = os.path.join(BASE_DIR, 'outputs')

    # Frame extraction settings
    FRAMES_PER_SECOND = 1
    FRAMES_PER_BATCH = 5

    # Gemini Models
    GEMINI_FLASH_MODEL = 'gemini-3-flash-preview'
    GEMINI_PRO_MODEL = 'gemini-3-pro-preview'

    # Fish Audio
    FISH_API_KEY = os.getenv('FISH_API_KEY')
    FISH_VOICE_ID = os.getenv('FISH_VOICE', '933563129e564b19a115bedd57b7406a')

    # Character Voice Mappings
    CHARACTER_VOICES = {
        'peter': os.getenv('FISH_VOICE', 'd75c270eaee14c8aa1e9e980cc37cf1b'),
        'spongebob': os.getenv('FISH_SPONGEBOB', 'c4b9d66aa7a24f5781684e6ae4b2fcfd'),
        'drake': os.getenv('FISH_DRAKE', '9ac5da5bee4c4036a9ccc3e46fd93a2f'),
        'joerogan': os.getenv('FISH_JOEROGAN', '0a8f443cf9c34f6f848e01ea7260c549'),
    }

    # Default character
    DEFAULT_CHARACTER = 'peter'

    # Assets Directory (for Docker, this will be /app/assets)
    ASSETS_DIR = os.getenv('ASSETS_DIR', os.path.join(BASE_DIR, 'assets'))

    # Character overlay images (use assets directory)
    @classmethod
    def get_character_image_path(cls, character: str) -> str:
        """Get the path to a character overlay image."""
        return os.path.join(cls.ASSETS_DIR, 'characters', f'{character}.png')

    # Legacy paths for backward compatibility
    PETER_PNG_PATH = property(lambda self: self.get_character_image_path('peter'))

    CHARACTER_IMAGES = {
        'peter': os.path.join(os.getenv('ASSETS_DIR', os.path.join(BASE_DIR, 'assets')), 'characters', 'peter.png'),
        'spongebob': os.path.join(os.getenv('ASSETS_DIR', os.path.join(BASE_DIR, 'assets')), 'characters', 'spongebob.png'),
        'drake': os.path.join(os.getenv('ASSETS_DIR', os.path.join(BASE_DIR, 'assets')), 'characters', 'drake.png'),
        'joerogan': os.path.join(os.getenv('ASSETS_DIR', os.path.join(BASE_DIR, 'assets')), 'characters', 'joerogan.png'),
    }

    # Character-specific overlay settings
    CHARACTER_OVERLAY_SETTINGS = {
        'peter': {'scale': 2.0, 'flip_orientation': False},
        'spongebob': {'scale': 1.0, 'flip_orientation': True},
        'drake': {'scale': 1.0, 'flip_orientation': False},
        'joerogan': {'scale': 1.5, 'flip_orientation': False},
    }

    # Output Video Dimensions (Portrait 9:16)
    OUTPUT_WIDTH = 1080
    OUTPUT_HEIGHT = 1920

    # Caption Styling
    CAPTION_FONT = 'Poppins'
    CAPTION_FONT_SIZE = 125
    CAPTION_COLOR = 'AAFF00'
    CAPTION_OUTLINE_COLOR = '000000'
    CAPTION_OUTLINE_WIDTH = 6
    CAPTION_POSITION_Y = 40
    CAPTION_POP_DURATION_MS = 100
    CAPTION_BOUNCE_SCALE = 110

    # Sound Effects (use assets directory)
    SFX_DIR = os.path.join(os.getenv('ASSETS_DIR', os.path.join(BASE_DIR, 'assets')), 'sfx')
    SFX_START = 'thump.wav'
    SFX_END = 'get_out.wav'
    SFX_START_END_VOLUME = 0.8
    SFX_INTERMEDIATE_VOLUME = 0.3

    # Google Cloud Speech-to-Text
    STT_ENABLED = os.getenv('STT_ENABLED', 'true').lower() == 'true'
    STT_LANGUAGE = os.getenv('STT_LANGUAGE', 'en-US')
    STT_MODEL = os.getenv('STT_MODEL', 'long')


class ProductionConfig(Config):
    """Production configuration for VM deployment."""

    DEBUG = False

    # In production, DATABASE_URL should be set via environment
    # pointing to the local PostgreSQL on the VM

    # CORS for Vercel frontend
    FRONTEND_URL = os.getenv('FRONTEND_URL', 'https://clashroast.vercel.app')

    # In Cloud Run Jobs, assets are at /app/assets
    ASSETS_DIR = os.getenv('ASSETS_DIR', '/app/assets')


class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG = True


def get_config():
    """Get the appropriate config based on FLASK_ENV."""
    env = os.getenv('FLASK_ENV', 'development')
    if env == 'production':
        return ProductionConfig()
    return DevelopmentConfig()
