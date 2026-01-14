"""
Video processing pipeline for Cloud Run Jobs.

This module contains the main processing pipeline that was previously
handled by Celery tasks. It's designed to run as a single long-running
job in Cloud Run Jobs.
"""
import os
from app.models import db, Video, FrameBatch, Commentary
from app.services.video_service import VideoService
from app.services.gemini_service import GeminiService
from app.services.merge_service import MergeService
from app.services.editing_service import EditingService
from app.services.fish_audio_service import FishAudioService
from app.services.video_editing_service import VideoEditingService
from app.services.gcs_service import gcs_service
from app.config import Config


def process_video_pipeline(video_id: int) -> dict:
    """
    Main pipeline to process a video from start to finish.

    This is the Cloud Run Jobs equivalent of the Celery task chain.
    It runs synchronously as a single job.

    Args:
        video_id: The ID of the video to process

    Returns:
        A dict with the processing result
    """
    video = Video.query.get(video_id)
    if not video:
        raise ValueError(f"Video not found: {video_id}")

    try:
        # Update status
        video.status = 'processing'
        db.session.commit()
        print(f"[Pipeline] Starting processing for video {video_id}")

        # Step 0: Download from GCS if needed
        video_path = os.path.join(Config.VIDEOS_DIR, video.filename)

        if video.gcs_input_uri:
            print(f"[Pipeline] Downloading video from GCS: {video.gcs_input_uri}")
            try:
                gcs_service.download_to_local(video.gcs_input_uri, video_path)
            except Exception as e:
                raise Exception(f"Failed to download from GCS: {str(e)}")
        elif not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found at {video_path}")

        # Calculate duration if not already set
        if not video.duration:
            video.duration = VideoService.get_video_duration(video_path)
            db.session.commit()
            print(f"[Pipeline] Video duration: {video.duration}s")

        # Step 1: Extract frames
        print("[Pipeline] Extracting frames...")
        frame_dir = os.path.join(Config.FRAMES_DIR, str(video_id))
        frame_info = VideoService.extract_frames(
            video_path,
            frame_dir,
            fps=Config.FRAMES_PER_SECOND
        )
        print(f"[Pipeline] Extracted {len(frame_info)} frames")

        # Step 2: Create batches
        batches = VideoService.create_frame_batches(
            frame_info,
            batch_size=Config.FRAMES_PER_BATCH
        )
        print(f"[Pipeline] Created {len(batches)} batches")

        # Step 3: Create FrameBatch records
        batch_records = []
        for i, batch in enumerate(batches):
            frame_batch = FrameBatch(
                video_id=video_id,
                batch_number=i,
                frame_paths=[f['path'] for f in batch],
                timestamps=[f['formatted_time'] for f in batch],
                status='pending'
            )
            db.session.add(frame_batch)
            db.session.flush()
            batch_records.append(frame_batch)
        db.session.commit()

        # Step 4: Analyze batches (sequentially in Cloud Run Jobs)
        print("[Pipeline] Analyzing frame batches...")
        gemini = GeminiService()
        for batch in batch_records:
            try:
                batch.status = 'processing'
                db.session.commit()

                frame_info_for_batch = [
                    {'path': path, 'formatted_time': ts}
                    for path, ts in zip(batch.frame_paths, batch.timestamps)
                ]

                response = gemini.analyze_frame_batch(frame_info_for_batch, video.deck_description)
                batch.analysis_response = response
                batch.status = 'completed'
                db.session.commit()
                print(f"[Pipeline] Batch {batch.batch_number} analyzed successfully")

            except Exception as e:
                # NEW: Catch the error, log it, and mark as failed/skipped
                batch.status = 'failed'
                batch.error_message = f"Batch failed (possibly 503): {str(e)}"
                db.session.commit()
                print(f"[Pipeline] WARNING: Skipping Batch {batch.batch_number} due to error: {e}")
                
                # Continue to the next batch instead of raising the exception
                continue

        # Step 5: Merge and generate commentary
        print("[Pipeline] Merging batch responses...")
        completed_batches = FrameBatch.query.filter_by(
            video_id=video_id,
            status='completed'
        ).order_by(FrameBatch.batch_number).all()

        if not completed_batches:
            raise Exception('All batches failed to process. Cannot generate commentary.')

        batch_responses = [b.analysis_response for b in completed_batches]
        merged_events = MergeService.merge_batch_responses(batch_responses)

        # Generate EDL
        print("[Pipeline] Generating EDL...")
        edl = EditingService.generate_edl(merged_events, video.duration or 180)
        filtered_events = EditingService.filter_events_by_edl(merged_events, edl)
        video.edl = edl
        db.session.commit()

        # Generate commentary
        print("[Pipeline] Generating commentary...")
        commentary_data = gemini.generate_commentary(
            filtered_events,
            video.deck_description,
            video.duration,
            video.character
        )

        full_text = " ".join([c['text'] for c in commentary_data.get('commentary', [])])

        commentary = Commentary(
            video_id=video_id,
            merged_events=merged_events,
            commentary_text=full_text,
            structured_commentary=commentary_data,
            clean_commentary_text=full_text,
            status='processing'
        )
        db.session.add(commentary)
        db.session.commit()

        # Step 6: Audio synthesis
        print("[Pipeline] Synthesizing audio...")
        try:
            tts = FishAudioService()
            updated_data = tts.synthesize_commentary_segments(
                commentary_data,
                video_id,
                video.character
            )
            commentary.structured_commentary = updated_data
            commentary.status = 'completed'
            db.session.commit()
            print("[Pipeline] Audio synthesis completed")
        except Exception as e:
            commentary.status = 'failed'
            commentary.error_message = f"Audio synthesis failed: {str(e)}"
            db.session.commit()
            raise

        # Step 7: Render final video
        print("[Pipeline] Rendering final video...")
        video.status = 'rendering'
        db.session.commit()

        source_path = os.path.join(Config.VIDEOS_DIR, video.filename)
        if not os.path.exists(source_path) and video.gcs_input_uri:
            gcs_service.download_to_local(video.gcs_input_uri, source_path)

        output_filename = f"final_{video.filename}"
        output_path = os.path.join(Config.OUTPUT_DIR, output_filename)

        VideoEditingService.render_final_video(
            source_path,
            video.edl,
            commentary.structured_commentary,
            output_path,
            video.character
        )

        video.final_video_path = output_path
        print(f"[Pipeline] Video rendered to {output_path}")

        # Generate thumbnail
        try:
            thumbnail_filename = f"thumb_{video.filename}.jpg"
            thumbnail_path = os.path.join(Config.OUTPUT_DIR, thumbnail_filename)
            VideoEditingService.extract_thumbnail(output_path, thumbnail_path)
            video.thumbnail_path = thumbnail_path

            gcs_thumb_name = f"{Config.GCS_THUMBNAIL_PREFIX}{thumbnail_filename}"
            gcs_service.upload_to_gcs(thumbnail_path, gcs_thumb_name)
            video.gcs_thumbnail_uri = gcs_thumb_name
            print("[Pipeline] Thumbnail generated and uploaded")
        except Exception as e:
            print(f"[Pipeline] Thumbnail generation failed (non-critical): {e}")

        # Upload final video to GCS
        try:
            gcs_object_name = gcs_service.upload_to_gcs(output_path)
            video.gcs_output_uri = gcs_object_name
            print(f"[Pipeline] Final video uploaded to GCS: {gcs_object_name}")
        except Exception as e:
            print(f"[Pipeline] Failed to upload output to GCS: {e}")

        video.status = 'completed'
        db.session.commit()
        print(f"[Pipeline] Processing completed for video {video_id}")

        return {'status': 'completed', 'video_id': video_id, 'path': output_path}

    except Exception as e:
        print(f"[Pipeline] Processing failed: {e}")
        video.status = 'failed'
        db.session.commit()
        raise
