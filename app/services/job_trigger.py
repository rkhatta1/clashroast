"""
Cloud Run Jobs trigger service.

Triggers video processing jobs on Google Cloud Run Jobs.
"""
import os
from typing import Optional

# Configuration
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "gp-uno")
REGION = os.getenv("GCP_LOCATION", "us-central1")
JOB_NAME = os.getenv("CLOUD_RUN_JOB_NAME", "clash-roast-processor")


def trigger_video_processing(video_id: str) -> Optional[str]:
    """
    Trigger a Cloud Run Job to process a video.

    Args:
        video_id: The ID of the video to process

    Returns:
        The operation name if successful, None if in development mode
    """
    # Check if we're in development mode (no Cloud Run)
    if os.getenv("FLASK_ENV") == "development":
        print(f"[DEV MODE] Would trigger Cloud Run Job for video_id={video_id}")
        # In development, fall back to Celery
        from app.tasks import process_video_task
        process_video_task.delay(int(video_id))
        return None

    try:
        from google.cloud import run_v2

        client = run_v2.JobsClient()
        job_path = f"projects/{PROJECT_ID}/locations/{REGION}/jobs/{JOB_NAME}"

        request = run_v2.RunJobRequest(
            name=job_path,
            overrides=run_v2.RunJobRequest.Overrides(
                container_overrides=[
                    run_v2.RunJobRequest.Overrides.ContainerOverride(
                        env=[run_v2.EnvVar(name="VIDEO_ID", value=str(video_id))]
                    )
                ]
            )
        )

        operation = client.run_job(request=request)
        print(f"Triggered Cloud Run Job for video_id={video_id}, operation={operation.operation.name}")
        return operation.operation.name

    except ImportError:
        print("google-cloud-run not installed, falling back to Celery")
        from app.tasks import process_video_task
        process_video_task.delay(int(video_id))
        return None
    except Exception as e:
        print(f"Failed to trigger Cloud Run Job: {e}")
        raise
