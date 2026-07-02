-- Add dashboard_token column to clients table for client-facing read-only view
ALTER TABLE clients ADD COLUMN IF NOT EXISTS dashboard_token UUID DEFAULT uuid_generate_v4() NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_clients_dashboard_token ON clients(dashboard_token);

-- Backfill any existing clients that don't have a token yet
UPDATE clients SET dashboard_token = uuid_generate_v4() WHERE dashboard_token IS NULL;
