try:
    from google.genai import types
    print(hasattr(types.Part, 'from_text'))
except Exception as e:
    print(e)
