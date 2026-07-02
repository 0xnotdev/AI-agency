-- Add outbound_offer to client_configs
ALTER TABLE client_configs
ADD COLUMN outbound_offer TEXT;
