class MergeService:
    @staticmethod
    def merge_batch_responses(batch_responses):
        """
        Merge all batch responses into a single coherent event list.
        
        Args:
            batch_responses: List of JSON responses from each batch
        
        Returns:
            Merged JSON object with deduplicated events
        """
        all_frames = []
        
        # Flatten all frames from all batches
        for batch in batch_responses:
            if isinstance(batch, list):
                all_frames.extend(batch)
        
        # Sort by timestamp
        all_frames.sort(key=lambda x: MergeService._parse_timestamp(x.get('timestamp', '0:00')))
        
        # Deduplicate and consolidate
        consolidated_events = []
        
        for frame in all_frames:
            # Extract actual events from frame
            if frame.get('new_card_played'):
                consolidated_events.append({
                    'timestamp': frame['timestamp'],
                    'match_timer': frame.get('match_timer'),
                    'type': 'card_played',
                    'player': frame['new_card_played']['player'],
                    'card': frame['new_card_played']['card'],
                    'position': frame['new_card_played']['position'],
                    'elixir_after': frame.get('elixir')
                })
            
            if frame.get('spell_active'):
                consolidated_events.append({
                    'timestamp': frame['timestamp'],
                    'match_timer': frame.get('match_timer'),
                    'type': 'spell_cast',
                    'details': frame['spell_active']
                })
            
            # Check for tower changes
            # This could be more sophisticated to detect actual damage events
        
        return {
            'all_frames': all_frames,
            'consolidated_events': consolidated_events,
            'metadata': {
                'total_frames': len(all_frames),
                'total_events': len(consolidated_events)
            }
        }
    
    @staticmethod
    def _parse_timestamp(timestamp_str):
        """Convert 'M:SS' to seconds for sorting."""
        try:
            parts = timestamp_str.split(':')
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            return 0
        except:
            return 0
