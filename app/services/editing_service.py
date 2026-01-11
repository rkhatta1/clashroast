from app.services.gemini_service import GeminiService

class EditingService:
    @staticmethod
    def generate_edl(merged_events, total_duration):
        """
        Generate the Edit Decision List for the video.
        
        Args:
            merged_events: List of match events.
            total_duration: Total duration of the video.
            
        Returns:
            Dict containing 'keep_segments'.
        """
        gemini = GeminiService()
        return gemini.generate_edl(merged_events, total_duration)
    
    @staticmethod
    def filter_events_by_edl(merged_events, edl):
        """
        Filter the full event list to only include events within the kept segments.
        This helps the commentary generation focus on what's actually shown.
        """
        keep_segments = edl.get('keep_segments', [])
        filtered_events = []
        
        for event in merged_events.get('consolidated_events', []):
            timestamp_str = event.get('timestamp', '0:00')
            timestamp = EditingService._parse_timestamp(timestamp_str)
            
            # Check if event falls into any keep segment
            keep = False
            for segment in keep_segments:
                if segment['start'] <= timestamp <= segment['end']:
                    keep = True
                    break
            
            if keep:
                filtered_events.append(event)
                
        return filtered_events
    
    @staticmethod
    def _parse_timestamp(timestamp_str):
        """Convert 'M:SS' to seconds."""
        if isinstance(timestamp_str, (int, float)):
            return float(timestamp_str)
            
        try:
            parts = str(timestamp_str).split(':')
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                 return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            return 0
        except:
            return 0
