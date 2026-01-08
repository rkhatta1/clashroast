import os
import subprocess
import json
from pathlib import Path
from app.config import Config

class VideoService:
    @staticmethod
    def get_video_duration(video_path):
        """Get video duration using ffprobe."""
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'json',
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)
        return float(data['format']['duration'])
    
    @staticmethod
    def extract_frames(video_path, output_dir, fps=1):
        """
        Extract frames from video at specified FPS.
        Returns list of frame info with timestamps.
        """
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        # Get video filename without extension
        video_name = Path(video_path).stem
        
        # Output pattern for frames
        output_pattern = os.path.join(output_dir, f"{video_name}_frame_%04d.jpg")
        
        # FFmpeg command to extract frames
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-vf', f'fps={fps}',
            '-q:v', '2',  # High quality
            output_pattern
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        
        # Get all extracted frames
        frames = sorted([
            f for f in os.listdir(output_dir)
            if f.startswith(f"{video_name}_frame_")
        ])
        
        # Calculate timestamps for each frame
        frame_info = []
        for i, frame in enumerate(frames):
            timestamp = i / fps  # seconds
            frame_info.append({
                'path': os.path.join(output_dir, frame),
                'timestamp': timestamp,
                'formatted_time': VideoService.format_timestamp(timestamp)
            })
        
        return frame_info
    
    @staticmethod
    def format_timestamp(seconds):
        """Convert seconds to M:SS format."""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"
    
    @staticmethod
    def create_frame_batches(frame_info, batch_size=5):
        """Group frames into batches."""
        batches = []
        for i in range(0, len(frame_info), batch_size):
            batch = frame_info[i:i + batch_size]
            batches.append(batch)
        return batches
