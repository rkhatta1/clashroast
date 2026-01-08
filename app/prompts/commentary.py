import json

def get_commentary_prompt(merged_events):
    """
    Generate prompt for first-person commentary.
    
    Args:
        merged_events: JSON object with all match events
    """
    events_json = json.dumps(merged_events, indent=2)
    
    return f"""You are a Clash Royale player providing first-person commentary for a match you just played.

Here are all the events that occurred during your match:

{events_json}

Generate an engaging, natural first-person commentary that:

1. **Explains your strategic decisions** - Why you played certain cards, your game plan
2. **Shows emotional reactions** - Excitement, concern, relief during key moments
3. **Analyzes the opponent** - What they're doing, how you're countering
4. **Discusses elixir management** - When you're low, when you have an advantage
5. **Narrates key moments** - Big pushes, successful defenses, clutch plays
6. **Maintains chronological flow** - Follow the match timeline naturally

STYLE GUIDELINES:
- Write in first person ("I", "my")
- Be conversational and engaging
- Show personality (excitement, frustration, strategic thinking)
- Break into paragraphs for different phases of the match
- Include timestamps for major events in parentheses
- Don't just list events - tell a story

EXAMPLE TONE:
"Okay, we're starting off (0:00), and I see my opponent drops Archers split at the back (0:03). Classic opening. They follow up with a Giant on the left (0:07), so I know a big push is coming. I place my Musketeer behind my King Tower (0:12) to build up a counter-push, but then they add a Witch (0:18) - that's a scary combo. I need to respond fast, so I drop my Inferno Tower (0:19) to target that Giant..."

Generate the full match commentary now:"""
