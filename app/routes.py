from flask import Blueprint, request, jsonify
from app.models import db, Video, FrameBatch, Commentary
from app.tasks import process_video_task
import os
from app.config import Config

api = Blueprint('api', __name__)

@api.route('/videos', methods=['POST'])
def create_video():
    """
    Create a new video processing job.

    Body: {
        "filename": "match1.mp4",
        "deck_description": "Optional description of the deck being played"
    }
    """
    data = request.json
    filename = data.get('filename')
    deck_description = data.get('deck_description')

    if not filename:
        return jsonify({'error': 'filename required'}), 400

    video_path = os.path.join(Config.VIDEOS_DIR, filename)
    if not os.path.exists(video_path):
        return jsonify({'error': 'Video file not found'}), 404

    # Create video record
    from app.services.video_service import VideoService
    duration = VideoService.get_video_duration(video_path)

    video = Video(
        filename=filename,
        duration=duration,
        deck_description=deck_description,
        status='pending'
    )
    db.session.add(video)
    db.session.commit()

    # Start processing
    process_video_task.delay(video.id)

    return jsonify({
        'id': video.id,
        'filename': video.filename,
        'deck_description': video.deck_description,
        'status': video.status
    }), 201

@api.route('/videos/<int:video_id>', methods=['GET'])
def get_video(video_id):
    """Get video processing status and results."""
    video = Video.query.get_or_404(video_id)
    
    response = {
        'id': video.id,
        'filename': video.filename,
        'duration': video.duration,
        'status': video.status,
        'created_at': video.created_at.isoformat(),
        'batches': []
    }
    
    # Include batch info
    for batch in video.frame_batches:
        response['batches'].append({
            'id': batch.id,
            'batch_number': batch.batch_number,
            'status': batch.status,
            'frame_count': len(batch.frame_paths)
        })
    
    # Include commentary if available
    if video.commentary:
        response['commentary'] = {
            'status': video.commentary.status,
            'text': video.commentary.commentary_text,
            'events_count': video.commentary.merged_events.get('metadata', {}).get('total_events') if video.commentary.merged_events else 0
        }
    
    return jsonify(response)

@api.route('/videos/<int:video_id>/commentary', methods=['GET'])
def get_commentary(video_id):
    """Get full commentary details."""
    video = Video.query.get_or_404(video_id)
    
    if not video.commentary:
        return jsonify({'error': 'Commentary not yet generated'}), 404
    
    return jsonify({
        'video_id': video.id,
        'status': video.commentary.status,
        'commentary_text': video.commentary.commentary_text,
        'merged_events': video.commentary.merged_events,
        'error_message': video.commentary.error_message
    })

@api.route('/videos', methods=['GET'])
def list_videos():
    """List all videos."""
    videos = Video.query.order_by(Video.created_at.desc()).all()
    
    return jsonify([{
        'id': v.id,
        'filename': v.filename,
        'status': v.status,
        'created_at': v.created_at.isoformat()
    } for v in videos])
