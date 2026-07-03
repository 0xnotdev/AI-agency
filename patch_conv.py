import os
content = open('app/services/conversation.py', 'r').read()
content = content.replace('\"error\": str(e), \"conversation_id\"', '\"error\": str(e) + \" | \" + repr(getattr(e, \"last_attempt\", None) and e.last_attempt.exception()), \"conversation_id\"')
open('app/services/conversation.py', 'w').write(content)
