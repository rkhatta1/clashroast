import os
from fishaudio import FishAudio
from fishaudio.types import TTSConfig, Prosody
from fishaudio.utils import save
from app.config import Config

class FishAudioService:
    def __init__(self):
        # Initialize client (reads from FISH_API_KEY environment variable automatically if not passed)
        # But for safety/explicitness in our Config class setup, we can pass it if supported,
        # or just rely on the env var being set in the process.
        # The SDK docs say "Initialize client (reads from FISH_API_KEY environment variable)"
        # We ensure os.environ has it or pass it explicitly if the SDK allows.
        # Looking at docs, FishAudio(api_key=...) might be supported or it just reads env.
        # We'll set the env var just in case Config loaded it from .env file but it wasn't exported.
        if Config.FISH_API_KEY:
            os.environ['FISH_API_KEY'] = Config.FISH_API_KEY

        self.client = FishAudio()
        os.makedirs(Config.AUDIO_DIR, exist_ok=True)

    def get_voice_id(self, character=None):
        """Get the Fish Audio voice ID for a character."""
        if character and character in Config.CHARACTER_VOICES:
            return Config.CHARACTER_VOICES[character]
        return Config.FISH_VOICE_ID  # Default fallback

    def synthesize_commentary_segments(self, commentary_data, video_id, character=None):
        """
        Convert commentary segments to speech files using Fish Audio.

        Args:
            commentary_data: Dict with 'commentary' list of {timestamp, text}
            video_id: Video ID
            character: Character key for voice selection (peter, spongebob, drake, joerogan)

        Returns:
            Updated commentary_data with 'audio_path' in each segment.
        """
        segments = commentary_data.get('commentary', [])

        # Create a subdir for this video's clips
        video_audio_dir = os.path.join(Config.AUDIO_DIR, str(video_id))
        os.makedirs(video_audio_dir, exist_ok=True)

        # Get voice ID for the selected character
        voice_id = self.get_voice_id(character)
        print(f"Using voice ID: {voice_id} for character: {character or 'default'}")

        # Define config for the voice
        tts_config = TTSConfig(
            reference_id=voice_id,
            format="mp3",
            latency="balanced"
        )
        
        for i, segment in enumerate(segments):
            text = segment['text']
            # Simple filename: seq_timestamp.mp3
            # Ensure timestamp is safe float/int
            ts_val = segment.get('timestamp', 0)
            safe_ts = str(int(float(ts_val))).zfill(4)
            filename = f"{i:03d}_{safe_ts}.mp3"
            output_path = os.path.join(video_audio_dir, filename)
            
            try:
                # Generate audio
                audio_bytes = self.client.tts.convert(
                    text=text,
                    config=tts_config
                )
                
                # Save audio
                save(audio_bytes, output_path)
                
                segment['audio_path'] = output_path
                
            except Exception as e:
                print(f"Error generating audio for segment {i} ({text}): {e}")
                segment['audio_path'] = None
                
        return {'commentary': segments}
