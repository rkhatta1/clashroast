from flask import Blueprint, request, jsonify
from app.models import db, Video, FrameBatch, Commentary
from app.tasks import process_video_task
from app.services.gcs_service import gcs_service
from app.config import Config
import os

api = Blueprint('api', __name__)

# Valid character options
VALID_CHARACTERS = list(Config.CHARACTER_VOICES.keys())

# Character display info for frontend
CHARACTER_INFO = {
    'peter': {'name': 'Peter Griffin', 'show': 'Family Guy'},
    'spongebob': {'name': 'SpongeBob', 'show': 'SpongeBob SquarePants'},
    'drake': {'name': 'Drake', 'show': 'Rapper'},
    'joerogan': {'name': 'Joe Rogan', 'show': 'JRE Podcast'},
}


@api.route('/characters', methods=['GET'])
def get_characters():
    """Get list of available characters for commentary."""
    characters = []
    for key in VALID_CHARACTERS:
        info = CHARACTER_INFO.get(key, {'name': key, 'show': ''})
        characters.append({
            'id': key,
            'name': info['name'],
            'show': info['show'],
        })
    return jsonify({'characters': characters, 'default': Config.DEFAULT_CHARACTER})

@api.route('/upload/init', methods=['POST'])
def init_upload():
    """
    Initialize a resumable upload session.

    Body: {
        "filename": "match1.mp4",
        "content_type": "video/mp4",
        "size": 1024000
    }
    """
    data = request.json
    filename = data.get('filename')
    content_type = data.get('content_type')
    size = data.get('size')

    if not all([filename, content_type, size]):
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        result = gcs_service.generate_upload_url(filename, content_type, size)
        return jsonify(result)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Failed to initialize upload'}), 500

@api.route('/videos', methods=['POST'])
def create_video():
    """
    Create a new video processing job.

    Mode 1 (Legacy/Direct): Upload complete, start processing immediately.
    Mode 2 (Pre-create): Create placeholder with status='uploading'.
    """
    data = request.json
    filename = data.get('filename')
    gcs_object_name = data.get('gcs_object_name')
    deck_description = data.get('deck_description')
    character = data.get('character', Config.DEFAULT_CHARACTER)
    status = data.get('status', 'pending') # 'pending' or 'uploading'

    if not filename:
        return jsonify({'error': 'filename required'}), 400

    # Validate character
    if character not in VALID_CHARACTERS:
        return jsonify({
            'error': f'Invalid character. Must be one of: {", ".join(VALID_CHARACTERS)}'
        }), 400

    video = Video(
        filename=filename,
        gcs_input_uri=gcs_object_name, # Can be None if uploading
        deck_description=deck_description,
        character=character,
        status=status
    )

    if gcs_object_name:
        # Check existence if provided
        if not gcs_service.check_object_exists(gcs_object_name):
             return jsonify({'error': 'Video file not found in storage'}), 404
    elif status != 'uploading':
        # If not uploading and no GCS object, check local (legacy)
        video_path = os.path.join(Config.VIDEOS_DIR, filename)
        if os.path.exists(video_path):
            from app.services.video_service import VideoService
            video.duration = VideoService.get_video_duration(video_path)
        else:
             return jsonify({'error': 'Video file not found'}), 404

    db.session.add(video)
    db.session.commit()

    # Start processing ONLY if pending (upload complete)
    if video.status == 'pending':
        process_video_task.delay(video.id)

    return jsonify({
        'id': video.id,
        'filename': video.filename,
        'character': video.character,
        'deck_description': video.deck_description,
        'status': video.status
    }), 201

@api.route('/videos/<int:video_id>/start', methods=['POST'])
def start_processing(video_id):
    """
    Start processing for an uploaded video.
    Body: { "gcs_object_name": "..." }
    """
    video = Video.query.get_or_404(video_id)
    data = request.json
    gcs_object_name = data.get('gcs_object_name')

    if not gcs_object_name:
        return jsonify({'error': 'gcs_object_name required'}), 400

    if not gcs_service.check_object_exists(gcs_object_name):
        return jsonify({'error': 'Video file not found in storage'}), 404

    video.gcs_input_uri = gcs_object_name
    video.status = 'pending'
    db.session.commit()

    process_video_task.delay(video.id)

    return jsonify({
        'id': video.id,
        'status': video.status
    })

@api.route('/videos/<int:video_id>', methods=['GET'])
def get_video(video_id):
    """Get video processing status and results."""
    video = Video.query.get_or_404(video_id)

    thumbnail_url = None
    if video.gcs_thumbnail_uri:
        try:
            thumbnail_url = gcs_service.generate_download_url(video.gcs_thumbnail_uri)
        except Exception:
            pass

    response = {
        'id': video.id,
        'filename': video.filename,
        'duration': video.duration,
        'status': video.status,
        'progress': video.progress if hasattr(video, 'progress') else 0, # Add progress field to model if needed
        'created_at': video.created_at.isoformat(),
        'deck_description': video.deck_description,
        'character': video.character,
        'thumbnailUrl': thumbnail_url,
        'batches': []
    }

    # Include batch info
    for batch in video.frame_batches:
        response['batches'].append({
            'id': batch.id,
            'batch_number': batch.batch_number,
            'status': batch.status,
            'frame_count': len(batch.frame_paths) if batch.frame_paths else 0
        })

    # Include commentary if available
    if video.commentary:
        response['commentary'] = {
            'status': video.commentary.status,
            'text': video.commentary.commentary_text,
            'events_count': video.commentary.merged_events.get('metadata', {}).get('total_events') if video.commentary.merged_events else 0
        }

    return jsonify(response)

@api.route('/videos/<int:video_id>/download', methods=['GET'])
def download_video(video_id):
    """Generate a download URL for the completed video."""
    video = Video.query.get_or_404(video_id)

    if video.status != 'completed':
        return jsonify({'error': 'Video processing not complete'}), 400

    if not video.gcs_output_uri and not video.final_video_path:
        return jsonify({'error': 'Output video not found'}), 404

    try:
        # If we have a GCS URI, generate a signed URL
        if video.gcs_output_uri:
            url = gcs_service.generate_download_url(video.gcs_output_uri)
            return jsonify({'download_url': url})
        else:
            # Fallback for local files (would need a static file serve endpoint, or upload to GCS now)
            # For now, let's try to upload it to GCS if it exists locally but not in GCS
            if video.final_video_path and os.path.exists(video.final_video_path):
                object_name = gcs_service.upload_to_gcs(video.final_video_path)
                video.gcs_output_uri = object_name
                db.session.commit()
                url = gcs_service.generate_download_url(object_name)
                return jsonify({'download_url': url})

            return jsonify({'error': 'Video file missing'}), 404

    except Exception as e:
        return jsonify({'error': f'Failed to generate download URL: {str(e)}'}), 500

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

    video_list = []
    for v in videos:
        thumbnail_url = None
        if v.gcs_thumbnail_uri:
            try:
                thumbnail_url = gcs_service.generate_download_url(v.gcs_thumbnail_uri)
            except Exception:
                pass

        video_list.append({
            'id': v.id,
            'filename': v.filename,
            'status': v.status,
            'created_at': v.created_at.isoformat(),
            'thumbnailUrl': thumbnail_url,
            'duration': v.duration
        })

    return jsonify(video_list)

@api.route('/videos/<int:video_id>', methods=['DELETE'])
def delete_video(video_id):
    """Delete a video and its resources."""
    video = Video.query.get_or_404(video_id)

    try:
        # 1. Delete from GCS (input and output)
        if video.gcs_input_uri:
            gcs_service.delete_object(video.gcs_input_uri)
        if video.gcs_output_uri:
            gcs_service.delete_object(video.gcs_output_uri)

        # 2. Delete local files (if any)
        # Assuming we clean up local files after upload/processing, but if not:
        if video.final_video_path and os.path.exists(video.final_video_path):
            os.remove(video.final_video_path)

        # 3. Delete from Database
        db.session.delete(video)
        db.session.commit()

        return jsonify({'message': 'Video deleted successfully'}), 200

    except Exception as e:
        print(f"Delete failed: {e}")
        return jsonify({'error': 'Failed to delete video'}), 500
