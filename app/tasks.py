from celery import Celery, chain, group
from app.config import Config
from app.models import db, Video, FrameBatch, Commentary
from app.services.video_service import VideoService
from app.services.gemini_service import GeminiService
from app.services.merge_service import MergeService
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
            
            # Step 1: Extract frames
            video_path = os.path.join(Config.VIDEOS_DIR, video.filename)
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
            # Define the group of analysis tasks
            analysis_group = group(
                analyze_frame_batch_task.s(batch_id) for batch_id in batch_ids
            )
            
            # Step 5: Chain the group with the merge task
            # Use .si() (immutable signature) so merge task doesn't receive the group's results as arguments,
            # since it fetches data from the DB anyway.
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
def analyze_frame_batch_task(self, batch_id):
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
            
            # Call Gemini
            gemini = GeminiService()
            response = gemini.analyze_frame_batch(frame_info)
            
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
    """Merge batch responses and generate final commentary."""
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
            
            # Generate commentary
            gemini = GeminiService()
            commentary_text = gemini.generate_commentary(merged_events)
            
            # Save commentary
            commentary = Commentary(
                video_id=video_id,
                merged_events=merged_events,
                commentary_text=commentary_text,
                status='completed'
            )
            db.session.add(commentary)
            
            video.status = 'completed'
            db.session.commit()
            
            return {'video_id': video_id, 'status': 'completed'}
            
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
