def get_frame_analysis_prompt(timestamps):
    """
    Generate prompt for frame batch analysis.
    
    Args:
        timestamps: List of formatted timestamps (e.g., ['0:05', '0:06', ...])
    """
    return f"""You are analyzing {len(timestamps)} consecutive frames from a Clash Royale match at timestamps: {', '.join(timestamps)}.

The frames are provided in chronological order. Analyze each frame carefully and extract match events according to the provided schema.

For EACH frame, identify:
1. **Elixir count** for the bottom player (read the pink/purple elixir bar - count the filled segments).
2. **Match timer** in the top center (format M:SS or MM:SS).
3. **Cards on battlefield** - what troops/buildings are visible and their approximate positions.
4. **New cards played** - compare with previous frame to detect newly placed cards (green placement indicator or newly appeared card).
5. **Tower HP** - visible damage state (full, damaged, critical, destroyed).
6. **Spell effects** - any spell animations.
7. **Cards in hand** - the 4 cards visible at the bottom.

IMPORTANT:
- Be precise with card names.
- If you can't identify something, use null.
- "new_card_played" should only be populated if a card is placed in THIS specific frame.
- Only report what you actually see."""