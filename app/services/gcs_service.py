"""
Google Cloud Storage service for handling video uploads and downloads.
"""
import os
import uuid
from datetime import timedelta
from google.cloud import storage
from app.config import Config
import google.auth
from google.auth.transport.requests import Request


class GCSService:
    """Service for interacting with Google Cloud Storage."""

    def __init__(self):
        self._client = None
        self._bucket = None

    @property
    def client(self):
        """Lazy-load the GCS client."""
        if self._client is None:
            self._client = storage.Client(project=Config.GCP_PROJECT_ID)
        return self._client

    @property
    def bucket(self):
        """Lazy-load the GCS bucket."""
        if self._bucket is None:
            self._bucket = self.client.bucket(Config.GCS_BUCKET_NAME)
        return self._bucket

    def generate_upload_url(self, filename: str, content_type: str, size: int) -> dict:
        """
        Generate a signed URL for resumable upload directly to GCS.

        Args:
            filename: Original filename
            content_type: MIME type of the file
            size: File size in bytes

        Returns:
            dict with upload_url, object_name, and expiration
        """
        # Validate file size
        if size > Config.MAX_FILE_SIZE:
            raise ValueError(f"File size exceeds maximum of {Config.MAX_FILE_SIZE // (1024*1024)}MB")

        # Generate unique object name
        file_ext = os.path.splitext(filename)[1]
        unique_id = str(uuid.uuid4())[:8]
        object_name = f"{Config.GCS_UPLOAD_PREFIX}{unique_id}_{filename}"

        blob = self.bucket.blob(object_name)

        # Create a resumable upload URL without origin restriction
        # (Signed URLs are already secure via cryptographic signature)
        url = blob.create_resumable_upload_session(
            content_type=content_type,
            size=size,
            timeout=3600,
        )

        return {
            'upload_url': url,
            'object_name': object_name,
            'expires_in': 3600,  # 1 hour
        }

    def generate_signed_upload_url(self, filename: str, content_type: str) -> dict:
        """
        Generate a signed URL for PUT upload to GCS.

        Args:
            filename: Original filename
            content_type: MIME type of the file

        Returns:
            dict with upload_url, object_name, and expiration
        """
        # Generate unique object name
        file_ext = os.path.splitext(filename)[1]
        unique_id = str(uuid.uuid4())[:8]
        object_name = f"{Config.GCS_UPLOAD_PREFIX}{unique_id}_{filename}"

        blob = self.bucket.blob(object_name)

        # Generate signed URL for upload
        credentials = self.client._credentials
        
        # 2. Ensure the credentials have a valid token
        if not credentials.valid:
            credentials.refresh(Request())

        # 3. Explicitly pass BOTH the email and the access token
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(hours=1),
            method="GET",
            service_account_email=credentials.service_account_email,
            access_token=credentials.token, # Force remote signing with this token
        )

        return {
            'upload_url': url,
            'object_name': object_name,
            'expires_in': 3600,
        }


    def generate_download_url(self, object_name: str, expiration_hours: int = 24) -> str:
        blob = self.bucket.blob(object_name)

        if not blob.exists():
            raise FileNotFoundError(f"Object {object_name} not found in bucket")
            
        # Get original filename for the user
        display_name = object_name.split('/')[-1]

        # Remote signing configuration
        credentials = self.client._credentials
        if not credentials.valid:
            credentials.refresh(Request())

        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(hours=expiration_hours),
            method="GET",
            service_account_email=credentials.service_account_email,
            access_token=credentials.token,
            # NEW: Force browser download with a specific filename
            response_disposition=f'attachment; filename="{display_name}"'
        )

        return url

    def download_to_local(self, object_name: str, local_path: str) -> str:
        """
        Download a file from GCS to local filesystem.

        Args:
            object_name: GCS object path
            local_path: Local destination path

        Returns:
            Local file path
        """
        blob = self.bucket.blob(object_name)

        # Ensure directory exists
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        blob.download_to_filename(local_path)

        return local_path

    def upload_to_gcs(self, local_path: str, object_name: str = None) -> str:
        """
        Upload a local file to GCS.

        Args:
            local_path: Path to local file
            object_name: Optional custom object name, otherwise derived from local path

        Returns:
            GCS object name
        """
        if object_name is None:
            filename = os.path.basename(local_path)
            unique_id = str(uuid.uuid4())[:8]
            object_name = f"{Config.GCS_OUTPUT_PREFIX}{unique_id}_{filename}"

        blob = self.bucket.blob(object_name)
        blob.upload_from_filename(local_path)

        return object_name

    def check_object_exists(self, object_name: str) -> bool:
        """Check if an object exists in the bucket."""
        blob = self.bucket.blob(object_name)
        return blob.exists()

    def get_object_metadata(self, object_name: str) -> dict:
        """Get metadata for an object."""
        blob = self.bucket.blob(object_name)
        blob.reload()

        return {
            'name': blob.name,
            'size': blob.size,
            'content_type': blob.content_type,
            'created': blob.time_created.isoformat() if blob.time_created else None,
            'updated': blob.updated.isoformat() if blob.updated else None,
        }

    def delete_object(self, object_name: str) -> bool:
        """Delete an object from the bucket."""
        blob = self.bucket.blob(object_name)

        if blob.exists():
            blob.delete()
            return True
        return False


# Singleton instance
gcs_service = GCSService()
