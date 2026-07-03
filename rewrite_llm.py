import json
import re

content = open('app/services/llm.py', 'r', encoding='utf-8').read()

# Replace if LLM_PROVIDER.lower() == "gemini" with "openrouter"
content = content.replace('settings.LLM_PROVIDER.lower() == "gemini"', 'settings.LLM_PROVIDER.lower() == "openrouter"')
content = content.replace('return _call_gemini(system_prompt, conversation_history, new_message, client_config, lead_name, lead_phone)', 'return _call_openrouter(system_prompt, conversation_history, new_message, client_config, lead_name, lead_phone)')

# Write the new function
openrouter_func = '''
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
    
    model = "meta-llama/llama-3.3-70b-instruct:free"
    
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
                        result = f"Error checking calendar: {str(e)}"
            elif tool_call.function.name == "book_meeting_tool":
                if not calendar_tokens:
                    result = "Error: Calendar is not connected."
                else:
                    try:
                        link = book_calendar_event(calendar_tokens, client_id, lead_name, lead_phone, args["start_time_iso"], args["end_time_iso"])
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
'''

# Delete the _call_gemini function completely
content = re.sub(r'def _call_gemini.*?return LLMResponse\.model_validate_json\(json_response\.text\)', openrouter_func, content, flags=re.DOTALL)

open('app/services/llm.py', 'w', encoding='utf-8').write(content)
