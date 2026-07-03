import logging
import json
from typing import List, Dict, Any
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential
from app.core.config import settings
from app.services.calendar import check_availability, book_calendar_event

logger = logging.getLogger(__name__)

class LLMResponse(BaseModel):
    reply_text: str
    handoff_required: bool

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def generate_reply(client_config: Dict[str, Any], conversation_history: List[Dict[str, Any]], new_message: str, lead_name: str, lead_phone: str) -> LLMResponse:
    """
    Calls the LLM to generate a reply. Now handles function calling for Calendar APIs.
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
2. Do not invent information. If the user asks something outside the scope of the FAQ or services, set `handoff_required` to true and apologize briefly.
3. If the user expresses frustration or asks to speak to a human, set `handoff_required` to true.
4. If the user asks to book a meeting:
   - Ask them what day and time they prefer.
   - When they give a time, call `check_availability_tool` to see if there are open slots (check a 4-8 hour window around their request).
   - If there are slots, offer them explicitly.
   - Once they confirm a specific slot, call `book_meeting_tool`.
   - Never book without explicitly checking availability and getting their confirmation of the exact time.

Respond in JSON format matching the schema.
    """
    
    if settings.LLM_PROVIDER.lower() == "gemini":
        return _call_gemini(system_prompt, conversation_history, new_message, client_config, lead_name, lead_phone)
    elif settings.LLM_PROVIDER.lower() == "anthropic":
        return _call_anthropic(system_prompt, conversation_history, new_message)
    else:
        raise ValueError(f"Unsupported LLM provider: {settings.LLM_PROVIDER}")


def _call_gemini(system_prompt: str, conversation_history: List[Dict[str, Any]], new_message: str, client_config: Dict[str, Any], lead_name: str, lead_phone: str) -> LLMResponse:
    import os
    from google import genai
    from google.genai import types
    
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set.")
        
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    
    # Define Tools bound to the client config
    calendar_tokens = client_config.get("google_calendar_tokens")
    client_id = client_config.get("client_id")
    
    def check_availability_tool(start_time_iso: str, end_time_iso: str) -> list[str]:
        """
        Checks availability on the calendar.
        Args:
            start_time_iso: ISO 8601 UTC string for the start of the time window to check (e.g., 2026-07-04T09:00:00Z)
            end_time_iso: ISO 8601 UTC string for the end of the time window to check
        Returns:
            List of available 30-minute slot start times in ISO format.
        """
        if not calendar_tokens:
            return ["Error: Calendar is not connected."]
        try:
            return check_availability(calendar_tokens, client_id, start_time_iso, end_time_iso)
        except Exception as e:
            return [f"Error checking calendar: {str(e)}"]

    def book_meeting_tool(start_time_iso: str, end_time_iso: str) -> str:
        """
        Books a meeting on the calendar.
        Args:
            start_time_iso: ISO 8601 UTC string for the meeting start time
            end_time_iso: ISO 8601 UTC string for the meeting end time (usually 30 mins after start)
        Returns:
            A string containing the success message and meeting link, or an error.
        """
        if not calendar_tokens:
            return "Error: Calendar is not connected."
        try:
            link = book_calendar_event(calendar_tokens, client_id, lead_name, lead_phone, start_time_iso, end_time_iso)
            return f"Success! Meeting booked. Link: {link}"
        except Exception as e:
            return f"Error booking meeting: {str(e)}"
            
    tools = [check_availability_tool, book_meeting_tool]
    
    contents = []
    # Build history
    for msg in conversation_history:
        role = "user" if msg["direction"] == "inbound" else "model"
        # We don't have tool call history stored in the DB right now, so we only pass text
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])]))
        
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=new_message)]))
    
    # We create a chat session because function calling may require multiple turns (Model calls tool -> we reply -> Model gives final answer)
    chat = client.chats.create(
        model='gemini-2.0-flash',
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.3,
            tools=tools
        )
    )
    
    # Send the history to the chat session manually if supported, but usually it's easier to just pass history in send_message.
    # Actually `client.chats.create` takes `history=contents[:-1]`, let's do that.
    chat = client.chats.create(
        model='gemini-2.0-flash',
        history=contents[:-1],
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.3,
            tools=tools
        )
    )
    
    response = chat.send_message(new_message)
    
    # Handle function calls loop
    while response.function_calls:
        for function_call in response.function_calls:
            logger.info(f"LLM called function: {function_call.name}")
            if function_call.name == "check_availability_tool":
                args = function_call.args
                result = check_availability_tool(args["start_time_iso"], args["end_time_iso"])
                # Send tool response back to the model
                response = chat.send_message(
                    types.Part.from_function_response(
                        name=function_call.name,
                        response={"result": result}
                    )
                )
            elif function_call.name == "book_meeting_tool":
                args = function_call.args
                result = book_meeting_tool(args["start_time_iso"], args["end_time_iso"])
                response = chat.send_message(
                    types.Part.from_function_response(
                        name=function_call.name,
                        response={"result": result}
                    )
                )
            else:
                response = chat.send_message(
                    types.Part.from_function_response(
                        name=function_call.name,
                        response={"error": "Unknown function"}
                    )
                )

    # Now the model has given its final text response.
    # Since we used tools, we couldn't force Structured Outputs (JSON Schema) easily in the same call in some SDK versions, 
    # but we can ask it for JSON or we can just do a second pass to extract the JSON.
    # Let's do a second pass to guarantee JSON format matching LLMResponse.
    
    final_text = response.text
    
    extraction_prompt = f"""
    Extract the response into the required JSON schema.
    The response text is:
    {final_text}
    """
    
    json_response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents=extraction_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=LLMResponse,
            temperature=0.1,
        )
    )
    
    return LLMResponse.model_validate_json(json_response.text)


def _call_anthropic(system_prompt: str, conversation_history: List[Dict[str, Any]], new_message: str) -> LLMResponse:
    raise NotImplementedError("Anthropic provider is not yet implemented.")
