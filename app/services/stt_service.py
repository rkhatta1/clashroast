"""
Google Cloud Speech-to-Text v2 Service for word-level timestamps.

Provides accurate word timing for captions by transcribing TTS audio.
"""

from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech
from app.config import Config


class STTService:
    """Service for getting word-level timestamps from audio using Google Cloud STT."""

    def __init__(self):
        """Initialize the Speech-to-Text client."""
        self.client = SpeechClient()
        self.project_id = Config.GCP_PROJECT_ID

    def get_word_timestamps(self, audio_path):
        """
        Get word-level timestamps from an audio file using Google Cloud STT.

        Args:
            audio_path: Path to audio file (MP3 or WAV)

        Returns:
            List of dicts: [{'word': str, 'start_time': float, 'end_time': float}, ...]
            Returns None if STT fails (for fallback to estimation)
        """
        if not self.project_id:
            print("STT: GCP_PROJECT_ID not configured, skipping STT")
            return None

        try:
            # Read audio file
            with open(audio_path, 'rb') as f:
                audio_content = f.read()

            # Configure recognition with word-level timestamps enabled
            config = cloud_speech.RecognitionConfig(
                auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
                language_codes=[Config.STT_LANGUAGE],
                model=Config.STT_MODEL,
                features=cloud_speech.RecognitionFeatures(
                    enable_word_time_offsets=True,  # Enable word timestamps
                    enable_automatic_punctuation=True,
                )
            )

            # Build request
            request = cloud_speech.RecognizeRequest(
                recognizer=f"projects/{self.project_id}/locations/global/recognizers/_",
                config=config,
                content=audio_content,
            )

            # Call STT API
            response = self.client.recognize(request=request)

            # Extract word timestamps from response
            word_timestamps = []

            for result in response.results:
                if not result.alternatives:
                    continue

                alternative = result.alternatives[0]

                # Check if words are available
                if hasattr(alternative, 'words') and alternative.words:
                    for word_info in alternative.words:
                        # Convert Duration to seconds
                        start_seconds = (
                            word_info.start_offset.seconds +
                            word_info.start_offset.microseconds / 1_000_000
                        )
                        end_seconds = (
                            word_info.end_offset.seconds +
                            word_info.end_offset.microseconds / 1_000_000
                        )

                        word_timestamps.append({
                            'word': word_info.word,
                            'start_time': start_seconds,
                            'end_time': end_seconds
                        })

            if word_timestamps:
                print(f"STT: Got {len(word_timestamps)} words from {audio_path}")
                return word_timestamps
            else:
                print(f"STT: No words detected in {audio_path}")
                return None

        except Exception as e:
            print(f"STT failed for {audio_path}: {e}")
            return None

    @staticmethod
    def group_words_into_chunks(word_timestamps, chunk_size=2):
        """
        Group word timestamps into caption chunks.

        Args:
            word_timestamps: List of {'word': str, 'start_time': float, 'end_time': float}
            chunk_size: Number of words per chunk (default 2)

        Returns:
            List of {'text': str, 'start': float, 'end': float}
        """
        if not word_timestamps:
            return []

        chunks = []

        for i in range(0, len(word_timestamps), chunk_size):
            chunk_words = word_timestamps[i:i + chunk_size]

            if not chunk_words:
                continue

            # Combine words into text
            chunk_text = ' '.join([w['word'] for w in chunk_words])

            # Get timing from first and last word in chunk
            start_time = chunk_words[0]['start_time']
            end_time = chunk_words[-1]['end_time']

            chunks.append({
                'text': chunk_text,
                'start': start_time,
                'end': end_time
            })

        return chunks
