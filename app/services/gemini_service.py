from google import genai
from google.genai import types
import json
import logging
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
)
from app.config import Config
from app.prompts.frame_analysis import get_frame_analysis_prompt
from app.prompts.commentary import get_commentary_prompt
from app.prompts.edl import get_edl_prompt

def is_retryable_error(exception):
    # Check for overloaded/rate limit strings in the exception message
    error_msg = str(exception).lower()
    return "503" in error_msg or "overloaded" in error_msg or "429" in error_msg

class GeminiService:
    def __init__(self):
        print("DEBUG: Initializing Client with Gemini API")
        self.client = genai.Client(
            api_key=Config.GEMINI_API_KEY
        )
    @retry(
        retry=retry_if_exception(is_retryable_error),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3)
    )
    def generate_edl(self, merged_events, total_duration):
        """
        Generate Edit Decision List using Gemini.
        """
        prompt = get_edl_prompt(merged_events, total_duration)
        
        response_schema = {
            'type': 'OBJECT',
            'properties': {
                'keep_segments': {
                    'type': 'ARRAY',
                    'items': {
                        'type': 'OBJECT',
                        'properties': {
                            'start': {'type': 'NUMBER'},
                            'end': {'type': 'NUMBER'},
                            'reason': {'type': 'STRING'}
                        },
                        'required': ['start', 'end', 'reason']
                    }
                }
            },
            'required': ['keep_segments']
        }
        
        response = self.client.models.generate_content(
            model=Config.GEMINI_FLASH_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
                response_schema=response_schema,
                temperature=1.0,
            )
        )
        
        try:
            return json.loads(response.text)
        except json.JSONDecodeError:
             # Fallback
            text = response.text.replace('```json', '').replace('```', '').strip()
            return json.loads(text)
    
    @retry(
        retry=retry_if_exception(is_retryable_error),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(5),
        before_sleep=lambda retry_state: print(f"Gemini overloaded, retrying... (Attempt {retry_state.attempt_number})")
    )
    def analyze_frame_batch(self, frame_batch_info, deck_description=None):
        """
        Analyze a batch of frames using Gemini.

        Args:
            frame_batch_info: List of dicts with 'path' and 'formatted_time'
            deck_description: Optional user-provided description of their deck
        """
        # Prepare content parts
        contents = []

        # Add prompt text
        timestamps = [frame['formatted_time'] for frame in frame_batch_info]
        prompt_text = get_frame_analysis_prompt(timestamps, deck_description)
        contents.append(prompt_text)
        
        # Add images
        for frame in frame_batch_info:
            with open(frame['path'], 'rb') as f:
                image_bytes = f.read()
            contents.append(types.Part.from_bytes(
                data=image_bytes,
                mime_type='image/jpeg'
            ))
            
        # Define response schema
        response_schema = {
            'type': 'ARRAY',
            'items': {
                'type': 'OBJECT',
                'properties': {
                    'timestamp': {'type': 'STRING'},
                    'match_timer': {'type': 'STRING'},
                    'elixir': {'type': 'INTEGER'},
                    'cards_in_hand': {
                        'type': 'ARRAY',
                        'items': {'type': 'STRING'}
                    },
                    'battlefield': {
                        'type': 'ARRAY',
                        'items': {
                            'type': 'OBJECT',
                            'properties': {
                                'card': {'type': 'STRING'},
                                'position': {'type': 'STRING'},
                                'player': {'type': 'STRING'}
                            }
                        }
                    },
                    'new_card_played': {
                        'type': 'OBJECT',
                        'properties': {
                            'player': {'type': 'STRING'},
                            'card': {'type': 'STRING'},
                            'position': {'type': 'STRING'}
                        },
                        'nullable': True
                    },
                    'towers': {
                        'type': 'OBJECT',
                        'properties': {
                            'opponent_left_princess': {'type': 'STRING'},
                            'opponent_right_princess': {'type': 'STRING'},
                            'opponent_king': {'type': 'STRING'},
                            'self_left_princess': {'type': 'STRING'},
                            'self_right_princess': {'type': 'STRING'},
                            'self_king': {'type': 'STRING'}
                        }
                    },
                    'spell_active': {'type': 'STRING', 'nullable': True},
                    'observations': {'type': 'STRING'}
                },
                'required': ['timestamp', 'match_timer', 'elixir', 'cards_in_hand', 'battlefield', 'towers', 'observations']
            }
        }

        # Generate response
        response = self.client.models.generate_content(
            model=Config.GEMINI_FLASH_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
                response_schema=response_schema,
                temperature=1.0,
                thinking_config=types.ThinkingConfig(thinking_level="medium")
            )
        )
        
        # Parse JSON
        try:
            if not response.text:
                print(f"Gemini response.text is empty. Candidates: {response.candidates}")
                # Return empty list or basic structure to avoid crashing the whole pipeline
                return []

            return json.loads(response.text)
        except json.JSONDecodeError:
            # Fallback if raw text returned (shouldn't happen with schema)
            if not response.text:
                return []
            text = response.text.replace('```json', '').replace('```', '').strip()
            return json.loads(text)

    @retry(
        retry=retry_if_exception(is_retryable_error),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3)
    )
    def generate_commentary(self, merged_events, deck_description=None, video_duration=None, character='peter'):
        """
        Generate first-person commentary using Gemini Pro.

        Args:
            merged_events: Merged frame analysis events
            deck_description: Optional user-provided description of their deck
            video_duration: Total video duration in seconds (used to constrain timestamps)
            character: Character key for prompt personality (peter, spongebob, drake, joerogan)

        Returns: Dict with 'commentary' list of {timestamp, text}.
        """
        prompt = get_commentary_prompt(merged_events, deck_description, video_duration, character)
        
        response_schema = {
            'type': 'OBJECT',
            'properties': {
                'commentary': {
                    'type': 'ARRAY',
                    'items': {
                        'type': 'OBJECT',
                        'properties': {
                            'timestamp': {'type': 'NUMBER'},
                            'text': {'type': 'STRING'}
                        },
                        'required': ['timestamp', 'text']
                    }
                }
            },
            'required': ['commentary']
        }
        
        response = self.client.models.generate_content(
            model=Config.GEMINI_PRO_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
                response_schema=response_schema,
                temperature=1.0,
                safety_settings=[
                    types.SafetySetting(
                        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                        threshold=types.HarmBlockThreshold.OFF,
                    ),
                ]
            )
        )
        
        try:
            if not response.text:
                print(f"Gemini commentary response.text is empty. Candidates: {response.candidates}")
                return {'commentary': []}

            return json.loads(response.text)
        except json.JSONDecodeError:
            if not response.text:
                return {'commentary': []}
            text = response.text.replace('```json', '').replace('```', '').strip()
            return json.loads(text)
