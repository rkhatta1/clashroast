import os
import subprocess
import json
import random
from app.config import Config
from app.services.caption_service import CaptionService

class VideoEditingService:
    # Peter Griffin overlay settings
    PETER_SCALE = 2.0   # Scale factor for the overlay
    PETER_ROTATION_DEG = 30  # Rotation angle in degrees (positive = counterclockwise)
    PETER_PEEK_AMOUNT = 0.6  # How much of Peter is visible (0.6 = 60% visible, 40% off-screen)
    PETER_Y_POSITION = 0.65  # Vertical position (0.55 = 55% down the screen)
    INTRO_SLIDE_DURATION = 0.4  # Duration of slide-in animation in seconds

    # Flash-in effect settings
    FLASH_DURATION = 0.7  # Duration of flash-in effect in seconds
    FLASH_INITIAL_BRIGHTNESS = 0.6  # Starting brightness boost (0-1 range, 0.6 = +60%)
    FLASH_INITIAL_GAMMA = 0.5  # Starting gamma (lower = brighter highlights)

    @staticmethod
    def render_final_video(video_path, edl, commentary_data, output_path):
        """
        Cut the video according to EDL and mix with timestamped commentary clips.
        Refines EDL to trim gaps larger than 2s between audio clips.
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        initial_segments = edl.get('keep_segments', [])
        if not initial_segments:
            raise ValueError("EDL is empty, cannot render video.")
        initial_segments.sort(key=lambda x: x['start'])

        # --- Phase 1: Calculate Audio Activity Zones (Original Timeline) ---
        # Merge only truly overlapping audio clips; any gap creates a jump cut
        audio_clips = []
        for clip in commentary_data.get('commentary', []):
            if not clip.get('audio_path'):
                continue

            ts = float(clip['timestamp'])
            duration = VideoEditingService._get_audio_duration(clip['audio_path'])

            # Define Active Zone (Exact Audio Duration)
            start = ts
            end = ts + duration

            audio_clips.append({'start': start, 'end': end, 'path': clip['audio_path'], 'orig_ts': ts})

        # Merge only overlapping audio zones; any gap = jump cut
        # When clips overlap, we keep only the first clip's timing since
        # overlapping clips will be skipped in Phase 4 anyway
        audio_clips.sort(key=lambda x: x['start'])
        audio_zones = []
        if audio_clips:
            current_start = audio_clips[0]['start']
            current_end = audio_clips[0]['end']

            for i in range(1, len(audio_clips)):
                clip = audio_clips[i]
                # Only merge if clips truly overlap (no gap tolerance)
                if clip['start'] <= current_end:
                    # Overlapping clip will be skipped - don't extend the zone
                    # Keep current_end as-is (first clip's end time)
                    pass
                else:
                    # Any gap = separate zone = jump cut
                    audio_zones.append({'start': current_start, 'end': current_end})
                    current_start = clip['start']
                    current_end = clip['end']
            audio_zones.append({'start': current_start, 'end': current_end})

        # --- Phase 2: Refine EDL (Intersect Action with Audio Zones) ---
        refined_segments = []
        if not audio_zones:
            refined_segments = initial_segments
        else:
            for seg in initial_segments:
                seg_start = seg['start']
                seg_end = seg['end']
                for zone in audio_zones:
                    inter_start = max(seg_start, zone['start'])
                    inter_end = min(seg_end, zone['end'])
                    if inter_start < inter_end:
                        refined_segments.append({'start': inter_start, 'end': inter_end})

        if not refined_segments:
             print("Warning: Refined EDL resulted in empty video. Falling back to original EDL.")
             refined_segments = initial_segments

        keep_segments = refined_segments

        # --- Phase 3: Timestamp Mapping ---
        mapped_audio_clips = []
        current_edit_time = 0.0
        segment_mappings = []

        for seg in keep_segments:
            duration = seg['end'] - seg['start']
            segment_mappings.append({
                'orig_start': seg['start'],
                'orig_end': seg['end'],
                'edit_start': current_edit_time
            })
            current_edit_time += duration

        total_edited_duration = current_edit_time

        for clip in commentary_data.get('commentary', []):
            if not clip.get('audio_path'):
                continue
            ts = float(clip['timestamp'])

            # Map timestamp
            mapped_ts = -1
            for mapping in segment_mappings:
                if mapping['orig_start'] <= ts <= mapping['orig_end']:
                    offset = ts - mapping['orig_start']
                    mapped_ts = mapping['edit_start'] + offset
                    break

            if mapped_ts >= 0:
                mapped_audio_clips.append({
                    'path': clip['audio_path'],
                    'start': mapped_ts
                })

        # --- Phase 4: Overlap Prevention with 1s Allowance ---
        mapped_audio_clips.sort(key=lambda x: x['start'])
        final_audio_clips = []
        kept_audio_paths = set()  # Track which audio clips are kept for captions
        last_end_time = 0.0

        for clip in mapped_audio_clips:
            duration = VideoEditingService._get_audio_duration(clip['path'])
            start_time = clip['start']

            # Allow 1.0s overlap
            if start_time < (last_end_time - 1.0):
                print(f"Skipping overlapping commentary clip at {start_time}s")
                continue

            final_audio_clips.append({
                'path': clip['path'],
                'delay': int(start_time * 1000) # ms
            })
            kept_audio_paths.add(clip['path'])
            last_end_time = start_time + duration

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
            # Each segment gets Peter Griffin overlay with alternating positions
            print("Rendering Stitched Video with Peter Griffin overlay...")

            segment_files = []
            segment_list_path = output_path + ".segments.txt"
            peter_path = Config.PETER_PNG_PATH

            for i, seg in enumerate(keep_segments):
                start = seg['start']
                end = seg['end']
                duration = end - start

                seg_filename = f"{output_path}.seg{i}.mp4"
                segment_files.append(seg_filename)

                # Build overlay filter for this segment
                overlay_filter = VideoEditingService._build_peter_overlay_filter(
                    segment_index=i,
                    segment_duration=duration,
                    is_first_segment=(i == 0)
                )

                cmd_seg = [
                    'ffmpeg', '-y',
                    '-ss', str(start),
                    '-t', str(duration),
                    '-i', video_path,
                    '-i', peter_path,
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
    def _build_peter_overlay_filter(segment_index, segment_duration, is_first_segment):
        """
        Build FFmpeg filter for Peter Griffin overlay.

        - Peter peeks from the sides of the screen with rotation
        - Left side: +30 degrees rotation, peeks from left edge
        - Right side: -30 degrees rotation (flipped), peeks from right edge
        - First segment: Slide in animation from off-screen
        - Subsequent segments: Static position, alternating left/right

        Args:
            segment_index: Index of the segment (0-based)
            segment_duration: Duration of this segment in seconds
            is_first_segment: Whether this is the first segment (for intro animation)

        Returns:
            FFmpeg filter_complex string
        """
        import math

        scale = VideoEditingService.PETER_SCALE
        rotation_deg = VideoEditingService.PETER_ROTATION_DEG
        peek_amount = VideoEditingService.PETER_PEEK_AMOUNT
        y_pos_ratio = VideoEditingService.PETER_Y_POSITION
        slide_duration = VideoEditingService.INTRO_SLIDE_DURATION

        # Convert degrees to radians for FFmpeg
        rotation_rad = rotation_deg * math.pi / 180

        # Determine position: even segments = left, odd segments = right
        is_left = (segment_index % 2 == 0)

        # Build the peter image filter chain:
        # 1. Scale
        # 2. Rotate (with transparent background, expand canvas to fit rotated image)
        # 3. Flip horizontally if on right side
        #
        # For rotation, we use: rotate=angle:c=0x00000000:ow=rotw(angle):oh=roth(angle)
        # - c=0x00000000 = transparent fill color
        # - ow/oh = output width/height to fit rotated image

        if is_left:
            # Left side: scale, then rotate +30 degrees (counterclockwise tilt)
            peter_filter = (
                f"[1:v]scale=iw*{scale}:ih*{scale},"
                f"rotate={rotation_rad}:c=0x00000000:ow=rotw({rotation_rad}):oh=roth({rotation_rad})[peter]"
            )
            # X position: partially off-screen to the left
            # Final x = -w * (1 - peek_amount), so 60% visible means x = -0.4*w
            x_final = f"-w*{1 - peek_amount}"
            # Animation: slide in from fully off-screen (-w) to final position
            x_start = "-w"
        else:
            # Right side: scale, flip, then rotate -30 degrees (clockwise tilt)
            peter_filter = (
                f"[1:v]scale=iw*{scale}:ih*{scale},"
                f"hflip,"
                f"rotate=-{rotation_rad}:c=0x00000000:ow=rotw(-{rotation_rad}):oh=roth(-{rotation_rad})[peter]"
            )
            # X position: partially off-screen to the right
            # Final x = W - w * peek_amount, so 60% visible means x = W - 0.6*w
            x_final = f"W-w*{peek_amount}"
            # Animation: slide in from fully off-screen (W) to final position
            x_start = "W"

        # Y position: centered at y_pos_ratio down the screen
        # y = H * y_pos_ratio - h/2 (center Peter at that vertical position)
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
                f"{peter_filter};"
                f"[0:v][peter]overlay=x={x_animated}:y={y_pos},"
                f"eq=brightness={brightness_expr}:gamma={gamma_expr}:eval=frame[v_out]"
            )
        else:
            # Static position
            overlay_filter = f"{peter_filter};[0:v][peter]overlay=x={x_final}:y={y_pos}[v_out]"

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
