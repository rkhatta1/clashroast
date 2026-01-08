from google import genai
from google.genai import types
import json
from app.config import Config
from app.prompts.frame_analysis import get_frame_analysis_prompt
from app.prompts.commentary import get_commentary_prompt

class GeminiService:
    def __init__(self):
        if Config.GEMINI_API_KEY:
            self.client = genai.Client(api_key=Config.GEMINI_API_KEY)
        else:
            # Fallback to Vertex AI if no API key (assuming gcloud auth is set)
            self.client = genai.Client(
                vertexai=True,
                project=Config.GCP_PROJECT_ID,
                location=Config.GCP_LOCATION
            )
    
    def analyze_frame_batch(self, frame_batch_info):
        """
        Analyze a batch of frames using Gemini.
        
        Args:
            frame_batch_info: List of dicts with 'path' and 'formatted_time'
        """
        # Prepare content parts
        contents = []
        
        # Add prompt text
        timestamps = [frame['formatted_time'] for frame in frame_batch_info]
        prompt_text = get_frame_analysis_prompt(timestamps)
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
            return json.loads(response.text)
        except json.JSONDecodeError:
            # Fallback if raw text returned (shouldn't happen with schema)
            text = response.text.replace('```json', '').replace('```', '').strip()
            return json.loads(text)

    def generate_commentary(self, merged_events):
        """
        Generate first-person commentary using Gemini Pro.
        """
        prompt = get_commentary_prompt(merged_events)
        
        response = self.client.models.generate_content(
            model=Config.GEMINI_PRO_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=1.0,
                thinking_config=types.ThinkingConfig(thinking_level="low")
            )
        )
        
        return response.text
