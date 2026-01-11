import os
import subprocess
import json
from app.config import Config


class CaptionService:
    """Service for generating word-chunk captions with pop animation."""

    # Number of words per caption chunk
    WORDS_PER_CHUNK = 3

    @staticmethod
    def get_audio_duration(file_path):
        """Get duration of audio file in seconds using ffprobe."""
        try:
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'json',
                file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            data = json.loads(result.stdout)
            return float(data['format']['duration'])
        except Exception as e:
            print(f"Error getting duration for {file_path}: {e}")
            return 0.0

    @staticmethod
    def estimate_word_timestamps(structured_commentary, segment_mappings, kept_audio_paths=None):
        """
        Estimate word-chunk timestamps from commentary segments.

        Args:
            structured_commentary: Dict with 'commentary' list of {timestamp, text, audio_path}
            segment_mappings: List of {orig_start, orig_end, edit_start} for timeline mapping
            kept_audio_paths: Set of audio paths that were kept (not skipped due to overlap)
                              If None, all clips are included.

        Returns:
            List of {text, start, end} with timestamps in the EDITED video timeline
        """
        all_chunks = []

        commentary_list = structured_commentary.get('commentary', [])

        for segment in commentary_list:
            text = segment.get('text', '')
            audio_path = segment.get('audio_path')
            orig_timestamp = float(segment.get('timestamp', 0))

            if not text or not audio_path:
                continue

            # Skip if this audio clip was filtered out due to overlap
            if kept_audio_paths is not None and audio_path not in kept_audio_paths:
                continue

            # Get audio duration
            audio_duration = CaptionService.get_audio_duration(audio_path)
            if audio_duration <= 0:
                continue

            # Split text into words
            words = text.split()
            if not words:
                continue

            # Map original timestamp to edited timeline
            mapped_start = CaptionService._map_timestamp(orig_timestamp, segment_mappings)
            if mapped_start < 0:
                # Segment was cut from final video
                continue

            # Group words into chunks of WORDS_PER_CHUNK
            chunks = CaptionService._chunk_words(words, CaptionService.WORDS_PER_CHUNK)

            # Calculate time per chunk
            time_per_chunk = audio_duration / len(chunks)

            # Generate chunk timestamps
            current_time = mapped_start
            for chunk in chunks:
                chunk_text = ' '.join(chunk)
                all_chunks.append({
                    'text': chunk_text,
                    'start': current_time,
                    'end': current_time + time_per_chunk
                })
                current_time += time_per_chunk

        return all_chunks

    @staticmethod
    def _chunk_words(words, chunk_size):
        """Split words list into chunks of chunk_size."""
        chunks = []
        for i in range(0, len(words), chunk_size):
            chunk = words[i:i + chunk_size]
            chunks.append(chunk)
        return chunks

    @staticmethod
    def _map_timestamp(orig_ts, segment_mappings):
        """
        Map a timestamp from original video to edited video timeline.

        Returns -1 if the timestamp falls outside kept segments.
        """
        for mapping in segment_mappings:
            if mapping['orig_start'] <= orig_ts <= mapping['orig_end']:
                offset = orig_ts - mapping['orig_start']
                return mapping['edit_start'] + offset
        return -1

    @staticmethod
    def generate_ass_subtitles(word_timestamps, output_path, video_width=1080, video_height=1920):
        """
        Generate ASS subtitle file with pop animation for each word chunk.

        Args:
            word_timestamps: List of {text, start, end}
            output_path: Path to write the .ass file
            video_width: Video width for positioning
            video_height: Video height for positioning
        """
        # ASS uses BGR color format, and colors are in &HBBGGRR format
        # Lime green #AAFF00 in RGB -> 00FFAA in BGR
        primary_color = f"&H00{CaptionService._rgb_to_bgr(Config.CAPTION_COLOR)}"
        outline_color = f"&H00{CaptionService._rgb_to_bgr(Config.CAPTION_OUTLINE_COLOR)}"

        font = Config.CAPTION_FONT
        font_size = Config.CAPTION_FONT_SIZE
        outline_width = Config.CAPTION_OUTLINE_WIDTH
        pop_duration = Config.CAPTION_POP_DURATION_MS
        bounce_scale = Config.CAPTION_BOUNCE_SCALE

        # Calculate Y position (ASS uses pixels from top)
        # Position at configured percentage from top
        y_pos = int(video_height * Config.CAPTION_POSITION_Y / 100)

        # ASS header
        # Bold is -1 (true), using BorderStyle 1 (outline + shadow)
        ass_content = f"""[Script Info]
Title: Word Captions
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,{font},{font_size},{primary_color},&H00FFFFFF,{outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,{outline_width},2,5,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        # Generate dialogue lines with pop animation for each chunk
        for chunk_data in word_timestamps:
            text = chunk_data['text']
            start = chunk_data['start']
            end = chunk_data['end']

            # Format timestamps as H:MM:SS.cc (centiseconds)
            start_str = CaptionService._format_ass_time(start)
            end_str = CaptionService._format_ass_time(end)

            # Pop animation: scale from 0 -> bounce_scale -> 100
            # \fscx and \fscy control X and Y scaling
            # \t(start,end,effect) applies animation over time
            #
            # Animation sequence:
            # 1. Start at 0% scale
            # 2. Pop to bounce_scale% over pop_duration ms
            # 3. Settle to 100% over another pop_duration/2 ms
            settle_duration = pop_duration // 2

            # Position override to set Y position
            # \pos(x,y) sets position, x=center of screen
            x_pos = video_width // 2

            animation = (
                f"{{\\pos({x_pos},{y_pos})"
                f"\\fscx0\\fscy0"
                f"\\t(0,{pop_duration},\\fscx{bounce_scale}\\fscy{bounce_scale})"
                f"\\t({pop_duration},{pop_duration + settle_duration},\\fscx100\\fscy100)}}"
            )

            # Escape special ASS characters in text
            escaped_text = text.replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}')

            ass_content += f"Dialogue: 0,{start_str},{end_str},Word,,0,0,0,,{animation}{escaped_text}\n"

        # Write the ASS file
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(ass_content)

        return output_path

    @staticmethod
    def _rgb_to_bgr(rgb_hex):
        """Convert RGB hex (RRGGBB) to BGR hex (BBGGRR) for ASS format."""
        r = rgb_hex[0:2]
        g = rgb_hex[2:4]
        b = rgb_hex[4:6]
        return f"{b}{g}{r}"

    @staticmethod
    def _format_ass_time(seconds):
        """Format seconds to ASS timestamp format: H:MM:SS.cc (centiseconds)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centisecs = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"
