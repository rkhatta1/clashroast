import os
from elevenlabs.client import ElevenLabs
from app.config import Config

class ElevenLabsService:
    def __init__(self):
        self.client = ElevenLabs(api_key=Config.ELEVENLABS_API_KEY)
        os.makedirs(Config.AUDIO_DIR, exist_ok=True)

    def synthesize_commentary_segments(self, commentary_data, video_id):
        """
        Convert commentary segments to speech files.
        
        Args:
            commentary_data: Dict with 'commentary' list of {timestamp, text}
            video_id: Video ID
            
        Returns:
            Updated commentary_data with 'audio_path' in each segment.
        """
        segments = commentary_data.get('commentary', [])
        
        # Create a subdir for this video's clips
        video_audio_dir = os.path.join(Config.AUDIO_DIR, str(video_id))
        os.makedirs(video_audio_dir, exist_ok=True)
        
        for i, segment in enumerate(segments):
            text = segment['text']
            # Simple filename: seq_timestamp.mp3
            safe_ts = str(int(segment['timestamp'])).zfill(4)
            filename = f"{i:03d}_{safe_ts}.mp3"
            output_path = os.path.join(video_audio_dir, filename)
            
            try:
                # Convert text to speech
                audio_generator = self.client.text_to_speech.convert(
                    text=text,
                    voice_id=Config.ELEVENLABS_VOICE_ID,
                    model_id="eleven_multilingual_v2",
                    output_format="mp3_44100_128",
                )
                
                with open(output_path, "wb") as f:
                    for chunk in audio_generator:
                        if chunk:
                            f.write(chunk)
                
                segment['audio_path'] = output_path
                
            except Exception as e:
                print(f"Error generating audio for segment {i}: {e}")
                segment['audio_path'] = None
                
        return {'commentary': segments}
