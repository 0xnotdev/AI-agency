import logging
from typing import List, Dict, Any, Tuple
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential
from app.core.config import settings

logger = logging.getLogger(__name__)

class LLMResponse(BaseModel):
    reply_text: str
    handoff_required: bool
    book_calendar: bool

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def generate_reply(client_config: Dict[str, Any], conversation_history: List[Dict[str, Any]], new_message: str) -> LLMResponse:
    """
    Calls the LLM to generate a reply, returning structured data.
    """
    system_prompt = f"""
You are an AI assistant for {client_config.get('business_name', 'a business')}.
Your role is to respond to incoming lead messages via SMS/WhatsApp/Email.

Business Services: {client_config.get('services', 'Not specified')}
Pricing: {client_config.get('pricing_notes', 'Not specified')}
FAQ: {client_config.get('faq', 'Not specified')}
Tone: {client_config.get('tone_instructions', 'professional and helpful')}

Instructions:
1. Provide a helpful, concise answer to the user's latest message based on the FAQ and services.
2. Do not invent information. If the user asks something outside the scope of the FAQ or services, set `handoff_required` to true and apologize briefly in `reply_text`.
3. If the user expresses frustration or asks to speak to a human, set `handoff_required` to true.
4. If the user explicitly asks to book a meeting or appointment, set `book_calendar` to true.

Respond in JSON format matching the schema.
    """
    
    if settings.LLM_PROVIDER.lower() == "gemini":
        return _call_gemini(system_prompt, conversation_history, new_message)
    elif settings.LLM_PROVIDER.lower() == "anthropic":
        return _call_anthropic(system_prompt, conversation_history, new_message)
    else:
        raise ValueError(f"Unsupported LLM provider: {settings.LLM_PROVIDER}")


def _call_gemini(system_prompt: str, conversation_history: List[Dict[str, Any]], new_message: str) -> LLMResponse:
    import os
    from google import genai
    from google.genai import types
    
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set.")
        
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    
    contents = []
    # Build history
    for msg in conversation_history:
        role = "user" if msg["direction"] == "inbound" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])]))
        
    # Append the new user message
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=new_message)]))
    
    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=LLMResponse,
            temperature=0.3,
        ),
    )
    
    if not response.text:
        raise ValueError("Empty response from Gemini")
        
    return LLMResponse.model_validate_json(response.text)


def _call_anthropic(system_prompt: str, conversation_history: List[Dict[str, Any]], new_message: str) -> LLMResponse:
    # Placeholder for Claude integration as per plan
    raise NotImplementedError("Anthropic provider is not yet implemented.")
