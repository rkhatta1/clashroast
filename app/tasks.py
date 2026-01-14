from celery import Celery, chain, group
from app.config import Config
from app.models import db, Video, FrameBatch, Commentary
from app.services.video_service import VideoService
from app.services.gemini_service import GeminiService
from app.services.merge_service import MergeService
from app.services.editing_service import EditingService
from app.services.fish_audio_service import FishAudioService
from app.services.video_editing_service import VideoEditingService
from app.services.gcs_service import gcs_service
import os

celery = Celery(
    'tasks',
    broker=Config.CELERY_BROKER_URL,
    backend=Config.CELERY_RESULT_BACKEND
)
celery.conf.update(
    broker_connection_retry_on_startup=True
)

@celery.task(bind=True)
def process_video_task(self, video_id):
    """Main task to orchestrate video processing."""
    from app import create_app
    app = create_app()

    with app.app_context():
        video = Video.query.get(video_id)
        if not video:
            return {'error': 'Video not found'}

        try:
            # Update status
            video.status = 'processing'
            db.session.commit()

            # Step 0: Download from GCS if needed
            video_path = os.path.join(Config.VIDEOS_DIR, video.filename)

            if video.gcs_input_uri:
                # Ensure filename is safe or use a UUID based name if collisions are a worry
                # For now assuming filename in DB is unique enough or we overwrite cache
                try:
                    gcs_service.download_to_local(video.gcs_input_uri, video_path)
                except Exception as e:
                    raise Exception(f"Failed to download from GCS: {str(e)}")
            elif not os.path.exists(video_path):
                raise FileNotFoundError(f"Video file not found at {video_path}")

            # Calculate duration if not already set (e.g. from GCS upload)
            if not video.duration:
                video.duration = VideoService.get_video_duration(video_path)
                db.session.commit()

            # Step 1: Extract frames
            frame_dir = os.path.join(Config.FRAMES_DIR, str(video_id))

            frame_info = VideoService.extract_frames(
                video_path,
                frame_dir,
                fps=Config.FRAMES_PER_SECOND
            )

            # Step 2: Create batches
            batches = VideoService.create_frame_batches(
                frame_info,
                batch_size=Config.FRAMES_PER_BATCH
            )

            # Step 3: Create FrameBatch records
            batch_ids = []
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
                batch_ids.append(frame_batch.id)

            db.session.commit()

            # Step 4: Process batches in parallel with Celery
            # Define the group of analysis tasks (pass deck_description for context)
            analysis_group = group(
                analyze_frame_batch_task.s(batch_id, video.deck_description) for batch_id in batch_ids
            )

            # Step 5: Chain the group with the merge task
            workflow = chain(
                analysis_group,
                merge_and_generate_commentary_task.si(video_id)
            )

            # Execute the workflow asynchronously
            workflow.apply_async()

            return {'status': 'processing_started', 'video_id': video_id}

        except Exception as e:
            video.status = 'failed'
            db.session.commit()
            raise

@celery.task(bind=True)
def analyze_frame_batch_task(self, batch_id, deck_description=None):
    """Analyze a single frame batch with Gemini Flash."""
    from app import create_app
    app = create_app()

    with app.app_context():
        batch = FrameBatch.query.get(batch_id)
        if not batch:
            return {'error': 'Batch not found'}

        try:
            batch.status = 'processing'
            db.session.commit()

            # Prepare frame info for Gemini
            frame_info = [
                {'path': path, 'formatted_time': ts}
                for path, ts in zip(batch.frame_paths, batch.timestamps)
            ]

            # Call Gemini with deck context
            gemini = GeminiService()
            response = gemini.analyze_frame_batch(frame_info, deck_description)

            # Save response
            batch.analysis_response = response
            batch.status = 'completed'
            db.session.commit()

            return {'batch_id': batch_id, 'status': 'completed'}

        except Exception as e:
            batch.status = 'failed'
            batch.error_message = str(e)
            db.session.commit()
            raise

@celery.task(bind=True)
def merge_and_generate_commentary_task(self, video_id):
    """Merge batch responses, generate EDL, commentary, and audio."""
    from app import create_app
    app = create_app()

    with app.app_context():
        video = Video.query.get(video_id)
        if not video:
            return {'error': 'Video not found'}

        try:
            # Get all completed batches
            batches = FrameBatch.query.filter_by(
                video_id=video_id,
                status='completed'
            ).order_by(FrameBatch.batch_number).all()

            if not batches:
                raise Exception('No completed batches found')

            # Merge responses
            batch_responses = [b.analysis_response for b in batches]
            merged_events = MergeService.merge_batch_responses(batch_responses)

            # --- Generate EDL ---
            # Create EditingService instance
            edl = EditingService.generate_edl(merged_events, video.duration or 180)

            # Filter events to only those in the kept segments
            filtered_events = EditingService.filter_events_by_edl(merged_events, edl)

            # Save EDL to video
            video.edl = edl
            db.session.commit()

            # --- Generate Commentary ---
            # This now returns a dict {'commentary': [{'timestamp': x, 'text': y}, ...]}
            gemini = GeminiService()
            commentary_data = gemini.generate_commentary(
                filtered_events,
                video.deck_description,
                video.duration,  # Pass video duration to constrain timestamps
                video.character  # Pass character for personality/voice
            )

            # Extract plain text for simple display
            full_text = " ".join([c['text'] for c in commentary_data.get('commentary', [])])

            # Save commentary initial state
            commentary = Commentary(
                video_id=video_id,
                merged_events=merged_events,
                commentary_text=full_text,
                structured_commentary=commentary_data, # Save raw structure
                clean_commentary_text=full_text,
                status='processing'
            )
            db.session.add(commentary)
            db.session.commit()

            # --- Audio Synthesis (Segments) ---
            try:
                tts = FishAudioService()
                # Synthesize each segment and get updated data with audio paths
                updated_data = tts.synthesize_commentary_segments(
                    commentary_data,
                    video_id,
                    video.character  # Pass character for voice selection
                )

                commentary.structured_commentary = updated_data
                commentary.status = 'completed'
                db.session.commit()
            except Exception as e:
                commentary.status = 'failed'
                commentary.error_message = f"Audio synthesis failed: {str(e)}"
                db.session.commit()
                raise

            # Step 6: Render Final Video
            render_final_video_task.delay(video_id)

            return {'video_id': video_id, 'status': 'audio_completed'}

        except Exception as e:
            video.status = 'failed'
            if not video.commentary:
                commentary = Commentary(
                    video_id=video_id,
                    status='failed',
                    error_message=str(e)
                )
                db.session.add(commentary)
            else:
                video.commentary.status = 'failed'
                video.commentary.error_message = str(e)

            db.session.commit()
            raise

@celery.task(bind=True)
def render_final_video_task(self, video_id):
    """Render the final video with cuts and audio."""
    from app import create_app
    app = create_app()

    with app.app_context():
        video = Video.query.get(video_id)
        if not video or not video.commentary or not video.edl:
            return {'error': 'Missing video, commentary or EDL'}

        try:
            video.status = 'rendering'
            db.session.commit()

            source_path = os.path.join(Config.VIDEOS_DIR, video.filename)

            # Ensure source video exists (it should if downloaded in step 1, but check again)
            if not os.path.exists(source_path) and video.gcs_input_uri:
                 gcs_service.download_to_local(video.gcs_input_uri, source_path)

            # Pass the structured commentary with audio paths
            commentary_data = video.commentary.structured_commentary

            output_filename = f"final_{video.filename}"
            output_path = os.path.join(Config.OUTPUT_DIR, output_filename)

            VideoEditingService.render_final_video(
                source_path,
                video.edl,
                commentary_data,
                output_path,
                video.character  # Pass character for overlay image
            )

            video.final_video_path = output_path

            # Generate Thumbnail
            try:
                thumbnail_filename = f"thumb_{video.filename}.jpg"
                thumbnail_path = os.path.join(Config.OUTPUT_DIR, thumbnail_filename)

                VideoEditingService.extract_thumbnail(output_path, thumbnail_path)
                video.thumbnail_path = thumbnail_path

                # Upload thumbnail to GCS
                gcs_thumb_name = f"{Config.GCS_THUMBNAIL_PREFIX}{thumbnail_filename}"
                gcs_service.upload_to_gcs(thumbnail_path, gcs_thumb_name)
                video.gcs_thumbnail_uri = gcs_thumb_name

            except Exception as e:
                print(f"Thumbnail generation failed: {e}")
                # Don't fail the whole task for thumbnail

            # Upload to GCS
            try:
                gcs_object_name = gcs_service.upload_to_gcs(output_path)
                video.gcs_output_uri = gcs_object_name
            except Exception as e:
                # Log error but don't fail the whole task if upload fails (can retry manually)
                print(f"Failed to upload output to GCS: {e}")

            video.status = 'completed'
            db.session.commit()

            return {'status': 'completed', 'path': output_path}

        except Exception as e:
            video.status = 'failed'
            print(f"Render failed: {e}")
            db.session.commit()
            raise
