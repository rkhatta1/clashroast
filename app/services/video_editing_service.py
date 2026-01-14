import os
import subprocess
import json
import random
from app.config import Config
from app.services.caption_service import CaptionService

class VideoEditingService:
    # Output dimensions (portrait 9:16)
    OUTPUT_WIDTH = Config.OUTPUT_WIDTH
    OUTPUT_HEIGHT = Config.OUTPUT_HEIGHT

    # Default character overlay settings (used if character not in config)
    DEFAULT_OVERLAY_SCALE = 2.0
    OVERLAY_ROTATION_DEG = 30  # Rotation angle in degrees (positive = counterclockwise)
    OVERLAY_PEEK_AMOUNT = 0.6  # How much of character is visible (0.6 = 60% visible, 40% off-screen)
    OVERLAY_Y_POSITION = 0.65  # Vertical position (0.65 = 65% down the screen)
    INTRO_SLIDE_DURATION = 0.4  # Duration of slide-in animation in seconds

    # Flash-in effect settings
    FLASH_DURATION = 0.7  # Duration of flash-in effect in seconds
    FLASH_INITIAL_BRIGHTNESS = 0.6  # Starting brightness boost (0-1 range, 0.6 = +60%)
    FLASH_INITIAL_GAMMA = 0.5  # Starting gamma (lower = brighter highlights)

    @staticmethod
    def extract_thumbnail(video_path, output_path, timestamp=None):
        """
        Extract a thumbnail from the video.

        Args:
            video_path: Path to the source video
            output_path: Path to save the thumbnail
            timestamp: Time in seconds (optional). If None, takes a frame from 20% into the video.
        """
        try:
            if timestamp is None:
                # Get duration first
                cmd_dur = [
                    'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1', video_path
                ]
                result = subprocess.run(cmd_dur, capture_output=True, text=True, check=True)
                try:
                    duration = float(result.stdout.strip())
                    timestamp = duration * 0.2  # 20% point often has good action
                except ValueError:
                    timestamp = 0.0 # Fallback

            cmd = [
                'ffmpeg', '-y',
                '-ss', str(timestamp),
                '-i', video_path,
                '-vframes', '1',
                '-update', '1',
                '-q:v', '2',  # High quality jpeg
                output_path
            ]
            subprocess.run(cmd, check=True)
            return output_path
        except Exception as e:
            print(f"Thumbnail extraction failed: {e}")
            raise

    @staticmethod
    def get_character_image_path(character=None):
        """Get the overlay image path for a character."""
        if character and character in Config.CHARACTER_IMAGES:
            path = Config.CHARACTER_IMAGES[character]
            if os.path.exists(path):
                return path
        # Fallback to peter
        return Config.PETER_PNG_PATH

    @staticmethod
    def get_character_overlay_settings(character=None):
        """Get overlay settings (scale, flip_orientation) for a character."""
        if character and character in Config.CHARACTER_OVERLAY_SETTINGS:
            return Config.CHARACTER_OVERLAY_SETTINGS[character]
        # Default settings
        return {'scale': VideoEditingService.DEFAULT_OVERLAY_SCALE, 'flip_orientation': False}

    @staticmethod
    def render_final_video(video_path, edl, commentary_data, output_path, character=None):
        """
        Cut the video according to EDL and mix with timestamped commentary clips.
        Refines EDL to trim gaps larger than 2s between audio clips.
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        print("\n" + "="*60)
        print("DEBUG: Video Editing Service - Render Final Video")
        print("="*60)

        initial_segments = edl.get('keep_segments', [])
        if not initial_segments:
            raise ValueError("EDL is empty, cannot render video.")
        initial_segments.sort(key=lambda x: x['start'])

        # Calculate max video duration from EDL
        max_video_time = max(seg['end'] for seg in initial_segments)

        print(f"\nInitial EDL Segments ({len(initial_segments)} segments):")
        for i, seg in enumerate(initial_segments):
            print(f"  Segment {i}: [{seg['start']:.2f}s - {seg['end']:.2f}s] ({seg['end'] - seg['start']:.2f}s)")
        print(f"\nMax video duration: {max_video_time:.2f}s")

        # --- Phase 1: Calculate Audio Activity Zones (Original Timeline) ---
        print("\n" + "="*60)
        print("DEBUG: Phase 1 - Audio Activity Zones")
        print("="*60)

        # Collect audio clips with their info
        audio_clips = []
        skipped_clips = []
        for clip in commentary_data.get('commentary', []):
            if not clip.get('audio_path'):
                continue

            ts = float(clip['timestamp'])

            # Filter out clips that start beyond video duration
            if ts >= max_video_time:
                skipped_clips.append({
                    'path': clip['audio_path'],
                    'timestamp': ts,
                    'reason': f'timestamp {ts:.2f}s exceeds video duration {max_video_time:.2f}s'
                })
                continue

            duration = VideoEditingService._get_audio_duration(clip['audio_path'])

            # Define Active Zone (Exact Audio Duration)
            start = ts
            end = ts + duration

            audio_clips.append({
                'start': start,
                'end': end,
                'path': clip['audio_path'],
                'orig_ts': ts,
                'duration': duration
            })

        if skipped_clips:
            print(f"\nWARNING: Skipped {len(skipped_clips)} clips with timestamps exceeding video duration:")
            for sc in skipped_clips:
                print(f"  - {os.path.basename(sc['path'])}: {sc['reason']}")

        print(f"\nAudio Clips (before merging): {len(audio_clips)}")
        for i, ac in enumerate(audio_clips):
            print(f"  Clip {i}: [{ac['start']:.2f}s - {ac['end']:.2f}s] - {os.path.basename(ac['path'])}")

        # Merge overlapping audio clips into zones
        # Track which clips are "primary" (zone starters) vs "absorbed" (merged into existing zone)
        audio_clips.sort(key=lambda x: x['start'])
        audio_zones = []
        primary_clips = []  # Clips that start each zone - these will be used for audio
        absorbed_clips = []  # Clips that overlap and are absorbed into zones

        if audio_clips:
            current_zone_start = audio_clips[0]['start']
            current_zone_end = audio_clips[0]['end']
            current_primary_clip = audio_clips[0]

            for i in range(1, len(audio_clips)):
                clip = audio_clips[i]
                # Only merge if clips truly overlap (no gap tolerance)
                if clip['start'] <= current_zone_end:
                    # Overlapping clip - absorb it, don't extend the zone
                    absorbed_clips.append(clip)
                    print(f"  -> Clip {os.path.basename(clip['path'])} absorbed into zone (overlaps)")
                else:
                    # Gap found - save current zone and start new one
                    audio_zones.append({
                        'start': current_zone_start,
                        'end': current_zone_end,
                        'primary_clip': current_primary_clip
                    })
                    primary_clips.append(current_primary_clip)
                    current_zone_start = clip['start']
                    current_zone_end = clip['end']
                    current_primary_clip = clip

            # Don't forget the last zone
            audio_zones.append({
                'start': current_zone_start,
                'end': current_zone_end,
                'primary_clip': current_primary_clip
            })
            primary_clips.append(current_primary_clip)

        print(f"\nMerged Audio Zones ({len(audio_zones)} zones):")
        for i, zone in enumerate(audio_zones):
            print(f"  Zone {i}: [{zone['start']:.2f}s - {zone['end']:.2f}s] ({zone['end'] - zone['start']:.2f}s)")
            print(f"           Primary clip: {os.path.basename(zone['primary_clip']['path'])}")

        print(f"\nPrimary clips (will be used): {len(primary_clips)}")
        print(f"Absorbed clips (will be skipped): {len(absorbed_clips)}")
        for ac in absorbed_clips:
            print(f"  - {os.path.basename(ac['path'])} at {ac['start']:.2f}s")

        # --- Phase 2: Refine EDL (Intersect Action with Audio Zones) ---
        print("\n" + "="*60)
        print("DEBUG: Phase 2 - Refine EDL (Intersect with Audio Zones)")
        print("="*60)

        refined_segments = []
        if not audio_zones:
            refined_segments = [{'start': s['start'], 'end': s['end'], 'primary_clip': None} for s in initial_segments]
            print("\nNo audio zones - using initial EDL segments as-is")
        else:
            for seg in initial_segments:
                seg_start = seg['start']
                seg_end = seg['end']
                for zone in audio_zones:
                    inter_start = max(seg_start, zone['start'])
                    inter_end = min(seg_end, zone['end'])
                    if inter_start < inter_end:
                        refined_segments.append({
                            'start': inter_start,
                            'end': inter_end,
                            'primary_clip': zone['primary_clip']
                        })

        if not refined_segments:
             print("Warning: Refined EDL resulted in empty video. Falling back to original EDL.")
             refined_segments = [{'start': s['start'], 'end': s['end'], 'primary_clip': None} for s in initial_segments]

        print(f"\nRefined EDL Segments ({len(refined_segments)} segments):")
        total_duration = 0
        for i, seg in enumerate(refined_segments):
            seg_dur = seg['end'] - seg['start']
            total_duration += seg_dur
            clip_name = os.path.basename(seg['primary_clip']['path']) if seg.get('primary_clip') else 'None'
            print(f"  Segment {i}: [{seg['start']:.2f}s - {seg['end']:.2f}s] ({seg_dur:.2f}s) -> {clip_name}")
        print(f"\nTotal refined duration: {total_duration:.2f}s")

        keep_segments = refined_segments

        # --- Phase 3: Simple Sequential Audio Placement ---
        # Each refined segment has ONE primary audio clip that plays at segment start
        print("\n" + "="*60)
        print("DEBUG: Phase 3 - Sequential Audio Placement")
        print("="*60)

        final_audio_clips = []
        kept_audio_paths = set()
        current_edit_time = 0.0
        segment_mappings = []

        print(f"\nPlacing audio clips sequentially...")

        for i, seg in enumerate(keep_segments):
            seg_duration = seg['end'] - seg['start']
            segment_mappings.append({
                'orig_start': seg['start'],
                'orig_end': seg['end'],
                'edit_start': current_edit_time
            })

            primary_clip = seg.get('primary_clip')
            if primary_clip:
                audio_name = os.path.basename(primary_clip['path'])
                audio_duration = primary_clip['duration']

                final_audio_clips.append({
                    'path': primary_clip['path'],
                    'delay': int(current_edit_time * 1000)  # ms
                })
                kept_audio_paths.add(primary_clip['path'])

                print(f"  Segment {i}: edit_start={current_edit_time:.2f}s")
                print(f"    ✓ Audio: {audio_name}")
                print(f"      Delay: {int(current_edit_time * 1000)}ms, Duration: {audio_duration:.2f}s")
                print(f"      Original ts: {primary_clip['orig_ts']:.2f}s")
            else:
                print(f"  Segment {i}: edit_start={current_edit_time:.2f}s (no audio)")

            current_edit_time += seg_duration

        total_edited_duration = current_edit_time

        print(f"\n--- Summary ---")
        print(f"Total segments: {len(keep_segments)}")
        print(f"Audio clips placed: {len(final_audio_clips)}")
        print(f"Total edited duration: {total_edited_duration:.2f}s")
        print("="*60 + "\n")

        # === Phase 5: Multi-Step Rendering to prevent OOM ===
        temp_voice_path = output_path + ".voice.wav"
        temp_video_path = output_path + ".video.mp4"

        try:
            # Step 1: Generate Voice Track with SFX (Audio Only)
            print("Rendering Voice Track with SFX...")

            # Build SFX list: start SFX, intermediate SFX at alternate zone ends, end SFX
            sfx_clips = VideoEditingService._build_sfx_list(
                audio_zones,
                segment_mappings,
                total_edited_duration
            )

            # Combine voice clips and SFX clips
            all_audio_clips = []

            # Add voice clips
            for clip in final_audio_clips:
                all_audio_clips.append({
                    'path': clip['path'],
                    'delay': clip['delay'],
                    'volume': 1.0  # Voice clips at full volume (mixed later)
                })

            # Add SFX clips
            for sfx in sfx_clips:
                all_audio_clips.append({
                    'path': sfx['path'],
                    'delay': sfx['delay'],
                    'volume': sfx['volume']
                })

            if not all_audio_clips:
                cmd_voice = [
                    'ffmpeg', '-y', '-f', 'lavfi', '-i', f'anullsrc=r=44100:cl=stereo:d={total_edited_duration}',
                    temp_voice_path
                ]
            else:
                voice_inputs = []
                voice_filter = []

                for i, clip in enumerate(all_audio_clips):
                    voice_inputs.extend(['-i', clip['path']])
                    # Apply volume and delay
                    voice_filter.append(
                        f"[{i}:a]volume={clip['volume']},adelay={clip['delay']}|{clip['delay']}[v{i}]"
                    )

                all_labels = "".join([f"[v{i}]" for i in range(len(all_audio_clips))])
                # normalize=0 prevents amix from dividing volume by number of inputs
                voice_filter.append(f"{all_labels}amix=inputs={len(all_audio_clips)}:dropout_transition=0:normalize=0[a_out]")

                cmd_voice = ['ffmpeg', '-y'] + voice_inputs + [
                    '-filter_complex', ";".join(voice_filter),
                    '-map', '[a_out]',
                    '-c:a', 'pcm_s16le',
                    temp_voice_path
                ]

            subprocess.run(cmd_voice, check=True)

            # Step 2: Render Stitched Video (Sequential Clips + Concat Demuxer)
            # Each segment gets character overlay with alternating positions
            character_name = character or 'peter'
            print(f"Rendering Stitched Video with {character_name} overlay...")

            segment_files = []
            segment_list_path = output_path + ".segments.txt"
            overlay_path = VideoEditingService.get_character_image_path(character)
            overlay_settings = VideoEditingService.get_character_overlay_settings(character)
            print(f"Using overlay image: {overlay_path}")
            print(f"Overlay settings: scale={overlay_settings['scale']}, flip_orientation={overlay_settings['flip_orientation']}")

            for i, seg in enumerate(keep_segments):
                start = seg['start']
                end = seg['end']
                duration = end - start

                seg_filename = f"{output_path}.seg{i}.mp4"
                segment_files.append(seg_filename)

                # Build overlay filter for this segment
                overlay_filter = VideoEditingService._build_character_overlay_filter(
                    segment_index=i,
                    segment_duration=duration,
                    is_first_segment=(i == 0),
                    scale=overlay_settings['scale'],
                    flip_orientation=overlay_settings['flip_orientation']
                )

                cmd_seg = [
                    'ffmpeg', '-y',
                    '-ss', str(start),
                    '-t', str(duration),
                    '-i', video_path,
                    '-i', overlay_path,
                    '-filter_complex', overlay_filter,
                    '-map', '[v_out]',
                    '-map', '0:a',
                    '-c:v', 'libx264', '-preset', 'fast',
                    '-c:a', 'aac',
                    seg_filename
                ]
                subprocess.run(cmd_seg, check=True)

            with open(segment_list_path, 'w') as f:
                for seg_file in segment_files:
                    f.write(f"file '{seg_file}'\n")

            cmd_concat = [
                'ffmpeg', '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', segment_list_path,
                '-c', 'copy',
                temp_video_path
            ]
            subprocess.run(cmd_concat, check=True)

            # Cleanup segments
            for seg_file in segment_files:
                if os.path.exists(seg_file): os.remove(seg_file)
            if os.path.exists(segment_list_path): os.remove(segment_list_path)

            # Step 2.5: Generate and Burn Captions
            print("Generating captions...")
            temp_subtitle_path = output_path + ".captions.ass"
            temp_video_with_subs_path = output_path + ".withsubs.mp4"

            # Get video dimensions for caption positioning
            video_width, video_height = VideoEditingService._get_video_dimensions(temp_video_path)

            # Generate word timestamps from commentary (only for kept audio clips)
            word_timestamps = CaptionService.estimate_word_timestamps(
                commentary_data,
                segment_mappings,
                kept_audio_paths
            )

            if word_timestamps:
                # Generate ASS subtitle file
                CaptionService.generate_ass_subtitles(
                    word_timestamps,
                    temp_subtitle_path,
                    video_width=video_width,
                    video_height=video_height
                )

                # Burn subtitles into video
                print("Burning captions into video...")
                cmd_subs = [
                    'ffmpeg', '-y',
                    '-i', temp_video_path,
                    '-vf', f"ass={temp_subtitle_path}",
                    '-c:v', 'libx264', '-preset', 'fast',
                    '-c:a', 'copy',
                    temp_video_with_subs_path
                ]
                subprocess.run(cmd_subs, check=True)

                # Replace temp video with subtitled version
                os.remove(temp_video_path)
                os.rename(temp_video_with_subs_path, temp_video_path)

                # Cleanup subtitle file
                if os.path.exists(temp_subtitle_path):
                    os.remove(temp_subtitle_path)
            else:
                print("No word timestamps generated, skipping captions.")

            # Step 3: Final Mix
            print("Rendering Final Mix...")
            # Volume levels: gameplay 50%, voiceover 90%
            # normalize=0 prevents volume changes from amix
            final_filter = [
                "[0:a]volume=0.5[a_game]",
                "[1:a]volume=1.5[a_voice]",
                "[a_game][a_voice]amix=inputs=2:duration=first:normalize=0[a_final]"
            ]

            cmd_final = [
                'ffmpeg', '-y',
                '-i', temp_video_path,
                '-i', temp_voice_path,
                '-filter_complex', ";".join(final_filter),
                '-map', '0:v',
                '-map', '[a_final]',
                '-c:v', 'copy',
                '-c:a', 'aac',
                output_path
            ]
            subprocess.run(cmd_final, check=True)

            # Cleanup
            if os.path.exists(temp_voice_path): os.remove(temp_voice_path)
            if os.path.exists(temp_video_path): os.remove(temp_video_path)

        except subprocess.CalledProcessError as e:
            print(f"FFmpeg Error: {e}")
            raise RuntimeError("FFmpeg processing failed")

        return output_path

    @staticmethod
    def _build_character_overlay_filter(segment_index, segment_duration, is_first_segment, scale=None, flip_orientation=False):
        """
        Build FFmpeg filter for scaling video to target dimensions and adding character overlay.

        - Video is scaled to fill 1080x1920 (portrait), cropping excess
        - Character peeks from the sides of the screen with rotation
        - Left side: +30 degrees rotation, peeks from left edge
        - Right side: -30 degrees rotation (flipped), peeks from right edge
        - First segment: Slide in animation from off-screen
        - Subsequent segments: Static position, alternating left/right

        Args:
            segment_index: Index of the segment (0-based)
            segment_duration: Duration of this segment in seconds
            is_first_segment: Whether this is the first segment (for intro animation)
            scale: Scale factor for the overlay image (default: DEFAULT_OVERLAY_SCALE)
            flip_orientation: If True, swap left/right sides (for pre-flipped images like spongebob)

        Returns:
            FFmpeg filter_complex string
        """
        import math

        # Target dimensions
        out_w = VideoEditingService.OUTPUT_WIDTH
        out_h = VideoEditingService.OUTPUT_HEIGHT

        if scale is None:
            scale = VideoEditingService.DEFAULT_OVERLAY_SCALE
        rotation_deg = VideoEditingService.OVERLAY_ROTATION_DEG
        peek_amount = VideoEditingService.OVERLAY_PEEK_AMOUNT
        y_pos_ratio = VideoEditingService.OVERLAY_Y_POSITION
        slide_duration = VideoEditingService.INTRO_SLIDE_DURATION

        # Convert degrees to radians for FFmpeg
        rotation_rad = rotation_deg * math.pi / 180

        # Determine position: even segments = left, odd segments = right
        # If flip_orientation is True, swap left and right
        is_left = (segment_index % 2 == 0)
        if flip_orientation:
            is_left = not is_left

        # Scale and crop filter to enforce output dimensions
        # scale2ref scales to fill the target, then crop centers it
        # Using scale with force_original_aspect_ratio=increase to fill, then crop to exact size
        scale_crop_filter = (
            f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h}[scaled]"
        )

        # Build the character image filter chain:
        # 1. Scale
        # 2. Rotate (with transparent background, expand canvas to fit rotated image)
        # 3. Flip horizontally if on right side
        #
        # For rotation, we use: rotate=angle:c=0x00000000:ow=rotw(angle):oh=roth(angle)
        # - c=0x00000000 = transparent fill color
        # - ow/oh = output width/height to fit rotated image

        if is_left:
            # Left side: scale, then rotate +30 degrees (counterclockwise tilt)
            char_filter = (
                f"[1:v]scale=iw*{scale}:ih*{scale},"
                f"rotate={rotation_rad}:c=0x00000000:ow=rotw({rotation_rad}):oh=roth({rotation_rad})[char]"
            )
            # X position: partially off-screen to the left
            # Final x = -w * (1 - peek_amount), so 60% visible means x = -0.4*w
            x_final = f"-w*{1 - peek_amount}"
            # Animation: slide in from fully off-screen (-w) to final position
            x_start = "-w"
        else:
            # Right side: scale, flip, then rotate -30 degrees (clockwise tilt)
            char_filter = (
                f"[1:v]scale=iw*{scale}:ih*{scale},"
                f"hflip,"
                f"rotate=-{rotation_rad}:c=0x00000000:ow=rotw(-{rotation_rad}):oh=roth(-{rotation_rad})[char]"
            )
            # X position: partially off-screen to the right
            # Final x = W - w * peek_amount, so 60% visible means x = W - 0.6*w
            x_final = f"W-w*{peek_amount}"
            # Animation: slide in from fully off-screen (W) to final position
            x_start = "W"

        # Y position: centered at y_pos_ratio down the screen
        # y = H * y_pos_ratio - h/2 (center character at that vertical position)
        y_pos = f"H*{y_pos_ratio}-h/2"

        if is_first_segment:
            # Animated slide in from side with ease-in
            # progress = min(t/duration, 1)
            # eased = progress^2 (ease-in)
            # x = x_start + (x_final - x_start) * eased
            #
            # For left: x = -w + (-w*(1-peek) - (-w)) * eased = -w + w*(peek) * eased = -w * (1 - peek * eased)
            # Simplified: x = x_start + (x_final - x_start) * eased
            # But FFmpeg expressions don't support variables well, so we compute directly
            #
            # Left:  x goes from -w to -w*(1-peek)
            #        x = -w + (w - w*(1-peek)) * eased = -w + w*peek * eased = -w*(1 - peek*eased)
            #        Actually: -w + (-w*(1-peek) - (-w)) * eased = -w + (w - w*(1-peek)) * eased
            #                = -w + w*peek * eased
            #
            # Right: x goes from W to W - w*peek
            #        x = W + (W - w*peek - W) * eased = W - w*peek*eased

            if is_left:
                x_animated = f"-w+w*{peek_amount}*pow(min(t/{slide_duration}\\,1)\\,2)"
            else:
                x_animated = f"W-w*{peek_amount}*pow(min(t/{slide_duration}\\,1)\\,2)"

            # Add flash-in effect: fade from white/bright to normal
            # Using eq filter with animated brightness and gamma
            flash_duration = VideoEditingService.FLASH_DURATION
            initial_brightness = VideoEditingService.FLASH_INITIAL_BRIGHTNESS
            initial_gamma = VideoEditingService.FLASH_INITIAL_GAMMA

            # Brightness eases from initial_brightness to 0 over flash_duration
            # Gamma eases from initial_gamma to 1 (normal) over flash_duration
            # Using circOut easing: eased = sqrt(1 - pow(1 - progress, 2))
            # For brightness: b = initial * (1 - eased)
            # For gamma: g = initial + (1 - initial) * eased

            # CircOut easing formula: sqrt(1 - pow(1 - min(t/duration, 1), 2))
            # eq filter brightness range is -1 to 1, gamma is 0.1 to 10
            circ_out_expr = f"sqrt(1-pow(1-min(t/{flash_duration}\\,1)\\,2))"
            brightness_expr = f"{initial_brightness}*(1-{circ_out_expr})"
            gamma_expr = f"{initial_gamma}+(1-{initial_gamma})*{circ_out_expr}"

            overlay_filter = (
                f"{scale_crop_filter};"
                f"{char_filter};"
                f"[scaled][char]overlay=x={x_animated}:y={y_pos},"
                f"eq=brightness={brightness_expr}:gamma={gamma_expr}:eval=frame[v_out]"
            )
        else:
            # Static position
            overlay_filter = f"{scale_crop_filter};{char_filter};[scaled][char]overlay=x={x_final}:y={y_pos}[v_out]"

        return overlay_filter

    @staticmethod
    def _get_audio_duration(file_path):
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
    def _get_video_dimensions(file_path):
        """Get video width and height using ffprobe."""
        try:
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height',
                '-of', 'json',
                file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            data = json.loads(result.stdout)
            stream = data['streams'][0]
            return int(stream['width']), int(stream['height'])
        except Exception as e:
            print(f"Error getting dimensions for {file_path}: {e}")
            # Default to 9:16 portrait (common for shorts)
            return 1080, 1920

    @staticmethod
    def _build_sfx_list(audio_zones, segment_mappings, total_edited_duration):
        """
        Build list of SFX clips to add to the voice track.

        Args:
            audio_zones: List of audio zones in original timeline
            segment_mappings: List of {orig_start, orig_end, edit_start} for timeline mapping
            total_edited_duration: Total duration of edited video in seconds

        Returns:
            List of {path, delay (ms), volume} for SFX clips
        """
        sfx_clips = []

        # Get SFX paths
        sfx_dir = Config.SFX_DIR
        start_sfx = os.path.join(sfx_dir, Config.SFX_START)
        end_sfx = os.path.join(sfx_dir, Config.SFX_END)
        start_end_volume = Config.SFX_START_END_VOLUME
        intermediate_volume = Config.SFX_INTERMEDIATE_VOLUME

        # Get list of intermediate SFX (all files except start and end)
        intermediate_sfx = []
        if os.path.exists(sfx_dir):
            for f in os.listdir(sfx_dir):
                if f.endswith(('.wav', '.mp3')) and f not in [Config.SFX_START, Config.SFX_END]:
                    intermediate_sfx.append(os.path.join(sfx_dir, f))

        # 1. Add start SFX at 0:00
        if os.path.exists(start_sfx):
            sfx_clips.append({
                'path': start_sfx,
                'delay': 0,
                'volume': start_end_volume
            })

        # 2. Add intermediate SFX at the END of alternate audio zones
        # SFX is timed to END at the zone end (plays during the last few seconds of the zone)
        for i, zone in enumerate(audio_zones):
            # Only add SFX at alternate zones (every other zone)
            if i % 2 != 0:  # Skip first, add at second, skip third, etc.
                continue

            # Skip the last zone (we'll add end SFX there instead)
            if i == len(audio_zones) - 1:
                continue

            # Map zone end time to edited timeline
            zone_end_original = zone['end']
            mapped_end = VideoEditingService._map_to_edited_timeline(
                zone_end_original, segment_mappings
            )

            if mapped_end >= 0 and intermediate_sfx:
                # Pick a random SFX
                sfx_path = random.choice(intermediate_sfx)
                # Get SFX duration so it ends at the zone end
                sfx_duration = VideoEditingService._get_audio_duration(sfx_path)
                # Start SFX early so it ends at zone end
                sfx_start = max(0, mapped_end - sfx_duration)
                sfx_clips.append({
                    'path': sfx_path,
                    'delay': int(sfx_start * 1000),  # Convert to ms
                    'volume': intermediate_volume
                })

        # 3. Add end SFX at the end of video
        if os.path.exists(end_sfx):
            # Get duration of end SFX to position it correctly
            end_sfx_duration = VideoEditingService._get_audio_duration(end_sfx)
            end_delay = max(0, (total_edited_duration - end_sfx_duration) * 1000)
            sfx_clips.append({
                'path': end_sfx,
                'delay': int(end_delay),
                'volume': start_end_volume
            })

        return sfx_clips

    @staticmethod
    def _map_to_edited_timeline(orig_ts, segment_mappings):
        """
        Map a timestamp from original video to edited video timeline.
        Returns -1 if the timestamp falls outside kept segments.
        """
        for mapping in segment_mappings:
            if mapping['orig_start'] <= orig_ts <= mapping['orig_end']:
                offset = orig_ts - mapping['orig_start']
                return mapping['edit_start'] + offset
        return -1
