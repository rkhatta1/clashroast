import json

def get_edl_prompt(merged_events, total_duration):
    """
    Generate prompt for creating an Edit Decision List (EDL).
    
    Args:
        merged_events: List of match events.
        total_duration: Total duration of the video in seconds.
    """
    events_json = json.dumps(merged_events, indent=2)
    
    return f"""You are a professional video editor for Clash Royale gameplay.
Your goal is to create an Edit Decision List (EDL) to trim out boring parts of the match (e.g., waiting for elixir, no units on the battlefield) while keeping all the action.

Total Video Duration: {total_duration} seconds.

Here is the log of events that occurred in the match:
{events_json}

INSTRUCTIONS:
1. Identify segments of the video to **KEEP**.
2. **KEEP** any segment where:
    - A card is played.
    - Units are on the battlefield.
    - Tower damage is occurring.
    - A spell is cast.
    - There is a high elixir count (potential push coming).
3. **CUT** segments where:
    - Both players are just waiting (leaking elixir).
    - No units are on the field and no cards are being played for > 3 seconds.
4. Add a buffer of 2-3 seconds before and after each key event to ensure context is preserved.
5. Merge overlapping or very close segments (less than 2 seconds apart).

OUTPUT FORMAT:
Return a JSON object containing a list of segments to keep.

```json
{{
  "keep_segments": [
    {{ "start": 0, "end": 15, "reason": "Intro and first card played" }},
    {{ "start": 25, "end": 45, "reason": "Opponent push and defense" }},
    {{ "start": 60, "end": {total_duration}, "reason": "Final minute action" }}
  ]
}}
```

Return ONLY the JSON object.
"""
