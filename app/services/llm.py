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
    from datetime import datetime
    
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    system_prompt = f"""You are an AI assistant for {client_config.get('business_name', 'a business')}.
Your role is to respond to incoming lead messages via SMS/WhatsApp/Email.

The current date and time is {current_datetime} (UTC). When booking or checking availability, strictly use dates based on this current time.

Business Services: {client_config.get('services', 'Not specified')}
Pricing: {client_config.get('pricing_notes', 'Not specified')}
FAQ: {client_config.get('faq', 'Not specified')}
Tone: {client_config.get('tone_instructions', 'professional and helpful')}

Instructions:
1. Provide a helpful, concise answer to the user's latest message based on the FAQ and services.
2. Do not invent information. If the user asks something outside the scope of the FAQ or services, set `handoff_required` to true and apologize briefly.
3. If the user expresses frustration or asks to speak to a human, set `handoff_required` to true.
4. If the user asks to book a meeting:
   - Ask them what day and time they prefer. Also ask for their name and business name if you don't already know it.
   - When they give a time, call `check_availability_tool` to see if there are open slots (check a 4-8 hour window around their request).
   - If there are slots, offer them explicitly.
   - Once they confirm a specific slot, call `book_meeting_tool`. Pass a descriptive `meeting_summary` using their name/business.
   - Never book without explicitly checking availability and getting their confirmation of the exact time.

Respond in JSON format matching the schema.
    """
    
    if settings.LLM_PROVIDER.lower() == "openrouter":
        return _call_openrouter(system_prompt, conversation_history, new_message, client_config, lead_name, lead_phone)
    elif settings.LLM_PROVIDER.lower() == "anthropic":
        return _call_anthropic(system_prompt, conversation_history, new_message)
    else:
        raise ValueError(f"Unsupported LLM provider: {settings.LLM_PROVIDER}")



def _call_openrouter(system_prompt: str, conversation_history: List[Dict[str, Any]], new_message: str, client_config: Dict[str, Any], lead_name: str, lead_phone: str) -> LLMResponse:
    import json
    from openai import OpenAI
    
    if not settings.OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY is not set.")
        
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=settings.OPENROUTER_API_KEY,
    )
    
    # Define Tools bound to the client config
    calendar_tokens = client_config.get("google_calendar_tokens")
    client_id = client_config.get("client_id")
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "check_availability_tool",
                "description": "Checks availability on the calendar.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_time_iso": {
                            "type": "string",
                            "description": "ISO 8601 UTC string for the start of the time window to check"
                        },
                        "end_time_iso": {
                            "type": "string",
                            "description": "ISO 8601 UTC string for the end of the time window to check"
                        }
                    },
                    "required": ["start_time_iso", "end_time_iso"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "book_meeting_tool",
                "description": "Books a meeting on the calendar.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_time_iso": {
                            "type": "string",
                            "description": "ISO 8601 UTC string for the meeting start time"
                        },
                        "end_time_iso": {
                            "type": "string",
                            "description": "ISO 8601 UTC string for the meeting end time (usually 30 mins after start)"
                        },
                        "meeting_summary": {
                            "type": "string",
                            "description": "A short summary for the calendar event, e.g. 'Meeting with Mr. Paresh from Agarwal Traders'"
                        }
                    },
                    "required": ["start_time_iso", "end_time_iso"]
                }
            }
        }
    ]
    
    messages = [{"role": "system", "content": system_prompt}]
    
    for msg in conversation_history:
        role = "user" if msg["direction"] == "inbound" else "assistant"
        messages.append({"role": role, "content": msg["content"]})
        
    messages.append({"role": "user", "content": new_message})
    
    model = "openai/gpt-4o-mini"
    
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        temperature=0.3
    )
    
    response_message = response.choices[0].message
    
    # Handle tool calls loop
    while response_message.tool_calls:
        messages.append(response_message) # Add the assistant's tool calls to the messages
        
        for tool_call in response_message.tool_calls:
            logger.info(f"LLM called function: {tool_call.function.name}")
            args = json.loads(tool_call.function.arguments)
            
            if tool_call.function.name == "check_availability_tool":
                if not calendar_tokens:
                    result = "Error: Calendar is not connected."
                else:
                    try:
                        slots = check_availability(calendar_tokens, client_id, args["start_time_iso"], args["end_time_iso"])
                        result = json.dumps(slots)
                    except Exception as e:
                        logger.error(f"Error checking calendar: {str(e)}", exc_info=True)
                        result = f"Error checking calendar: {str(e)}"
            elif tool_call.function.name == "book_meeting_tool":
                if not calendar_tokens:
                    result = "Error: Calendar is not connected."
                else:
                    try:
                        link = book_calendar_event(calendar_tokens, client_id, lead_name, lead_phone, args["start_time_iso"], args["end_time_iso"], args.get("meeting_summary"))
                        result = f"Success! Meeting booked. Link: {link}"
                    except Exception as e:
                        result = f"Error booking meeting: {str(e)}"
            else:
                result = "Error: Unknown function"
                
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.function.name,
                "content": result
            })
            
        # Call the model again with the tool responses
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=0.3
        )
        response_message = response.choices[0].message
        
    final_text = response_message.content or ""
    
    # Second pass for JSON extraction since OpenRouter free models might not perfectly support response_format={"type": "json_schema"}
    extraction_prompt = f"""
    Extract the following response into JSON matching this schema exactly:
    {{
      "reply_text": "The final message to send to the user",
      "handoff_required": boolean indicating if a human needs to take over
    }}
    
    The response text is:
    {final_text}
    
    Return ONLY valid JSON.
    """
    
    json_response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": extraction_prompt}],
        response_format={"type": "json_object"},
        temperature=0.1
    )
    
    try:
        return LLMResponse.model_validate_json(json_response.choices[0].message.content)
    except Exception as e:
        logger.error(f"Failed to parse JSON: {json_response.choices[0].message.content}")
        # Fallback
        return LLMResponse(reply_text=final_text, handoff_required=True)



def _call_anthropic(system_prompt: str, conversation_history: List[Dict[str, Any]], new_message: str) -> LLMResponse:
    raise NotImplementedError("Anthropic provider is not yet implemented.")
