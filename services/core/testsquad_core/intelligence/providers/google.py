import google.generativeai as genai
from typing import List
from testsquad_shared.models import LLMRequest, LLMResponse, LLMModelInfo
from testsquad_core.intelligence.providers.base import BaseProvider

class GoogleProvider(BaseProvider):
    def __init__(self, api_key: str):
        super().__init__(api_key)
        genai.configure(api_key=self.api_key)

    async def list_models(self) -> List[LLMModelInfo]:
        try:
            models = []
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    # Clean up model name (remove 'models/')
                    name = m.name.replace('models/', '')
                    models.append(LLMModelInfo(
                        name=name, 
                        description=m.description, 
                        context_window=m.input_token_limit
                    ))
            return models
        except Exception as e:
            # Fallback to defaults if list_models fails (e.g., auth error)
            return [
                LLMModelInfo(name="gemini-1.5-pro", description="Google High-Reasoning Model", context_window=1000000),
                LLMModelInfo(name="gemini-1.5-flash", description="Google Fast/Cost-Effective Model", context_window=1000000)
            ]

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model_id = request.model_name
        if not model_id.startswith("models/"):
            model_id = f"models/{model_id}"
            
        model = genai.GenerativeModel(model_id)
        
        # Configure safety and generation params
        generation_config = genai.types.GenerationConfig(
            max_output_tokens=request.max_tokens,
            temperature=request.temperature
        )
        
        # Minimize false-positive blocks for code analysis
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
        
        # Using async generation to avoid blocking and allow better timeout handling
        response = await model.generate_content_async(
            request.prompt,
            generation_config=generation_config,
            safety_settings=safety_settings
        )
        
        try:
            content = response.text
        except ValueError:
            # Handle potential blockages or empty responses
            if response.candidates:
                candidate = response.candidates[0]
                if candidate.content.parts:
                    content = candidate.content.parts[0].text
                else:
                    content = f"Error: Candidate returned but has no text parts. Safety flags: {candidate.safety_ratings}"
            else:
                content = "Error: No candidates returned from model. Possible safety block or timeout."
                
        return LLMResponse(
            content=content,
            model_name=request.model_name,
            provider_name="Google",
            token_usage={"total_tokens": 0}
        )
