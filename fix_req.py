content = open('requirements.txt', 'r').read()
content = content.replace('google-genai', 'openai')
open('requirements.txt', 'w', encoding='utf-8').write(content)
