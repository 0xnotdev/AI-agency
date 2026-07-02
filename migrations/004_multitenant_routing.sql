-- Add columns to support exact-match inbound routing
ALTER TABLE client_configs ADD COLUMN IF NOT EXISTS whatsapp_phone_number_id TEXT;
ALTER TABLE client_configs ADD COLUMN IF NOT EXISTS inbound_email_address TEXT;

-- Create unique indexes to prevent collision across clients (where not null)
CREATE UNIQUE INDEX IF NOT EXISTS idx_client_configs_whatsapp ON client_configs(whatsapp_phone_number_id) WHERE whatsapp_phone_number_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_client_configs_email ON client_configs(inbound_email_address) WHERE inbound_email_address IS NOT NULL;
