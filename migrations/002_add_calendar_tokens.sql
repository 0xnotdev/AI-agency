-- Add Google Calendar tokens to client_configs
ALTER TABLE client_configs 
ADD COLUMN google_calendar_tokens JSONB DEFAULT NULL;

-- Add external_message_id to messages for webhook idempotency
ALTER TABLE messages
ADD COLUMN external_message_id TEXT UNIQUE;

-- We can also index external_message_id for faster duplicate lookups
CREATE INDEX idx_messages_external_message_id ON messages(external_message_id);
