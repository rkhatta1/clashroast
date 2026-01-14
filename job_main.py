"""
Cloud Run Job entry point for video processing.

This replaces the Celery worker for production deployments.
The job receives a VIDEO_ID environment variable and processes that video.
"""
import os
import sys


def main():
    video_id = os.environ.get("VIDEO_ID")
    if not video_id:
        print("ERROR: VIDEO_ID environment variable required")
        sys.exit(1)

    print(f"Starting video processing for video_id={video_id}")

    # Import here to avoid loading Flask app before env vars are set
    from app import create_app
    from app.services.video_pipeline import process_video_pipeline

    app = create_app()
    with app.app_context():
        try:
            process_video_pipeline(int(video_id))
            print(f"SUCCESS: Completed processing video {video_id}")
        except Exception as e:
            print(f"ERROR: Failed to process video {video_id}: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    main()
