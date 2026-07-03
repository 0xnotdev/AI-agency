-- Create campaigns table
CREATE TABLE IF NOT EXISTS campaigns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'completed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Update leads table to link to campaigns
ALTER TABLE leads 
ADD COLUMN IF NOT EXISTS campaign_id UUID REFERENCES campaigns(id) ON DELETE SET NULL;

-- Enable Row Level Security
ALTER TABLE campaigns ENABLE ROW LEVEL SECURITY;

-- Policies for campaigns
CREATE POLICY "Clients can view own campaigns" ON campaigns
    FOR SELECT USING (auth.uid() = client_id);

CREATE POLICY "Clients can insert own campaigns" ON campaigns
    FOR INSERT WITH CHECK (auth.uid() = client_id);

CREATE POLICY "Clients can update own campaigns" ON campaigns
    FOR UPDATE USING (auth.uid() = client_id);
