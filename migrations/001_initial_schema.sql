-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Clients table
CREATE TABLE clients (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    business_name TEXT NOT NULL,
    niche TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'churned')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Client configs
CREATE TABLE client_configs (
    client_id UUID PRIMARY KEY REFERENCES clients(id) ON DELETE CASCADE,
    services JSONB DEFAULT '{}',
    pricing_notes JSONB DEFAULT '{}',
    faq JSONB DEFAULT '{}',
    tone_instructions TEXT,
    booking_link TEXT,
    business_hours JSONB DEFAULT '{}'
);

-- Leads
CREATE TABLE leads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    external_lead_id TEXT,
    name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    source TEXT NOT NULL CHECK (source IN ('inbound', 'reactivation')),
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'contacted', 'replied', 'booked', 'dead')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_contacted_at TIMESTAMPTZ,
    UNIQUE (client_id, external_lead_id)
);

-- Conversations
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    channel TEXT NOT NULL CHECK (channel IN ('whatsapp', 'email')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'handed_off', 'closed'))
);

-- Messages
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    llm_metadata JSONB
);

-- Events
CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    payload JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Row-Level Security

ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE events ENABLE ROW LEVEL SECURITY;

-- Policies

-- Clients can read their own client row
CREATE POLICY "Clients can view own data" ON clients
    FOR SELECT USING (auth.uid() = id);

-- Clients can read/write their own config
CREATE POLICY "Clients can view own config" ON client_configs
    FOR SELECT USING (auth.uid() = client_id);
CREATE POLICY "Clients can insert own config" ON client_configs
    FOR INSERT WITH CHECK (auth.uid() = client_id);
CREATE POLICY "Clients can update own config" ON client_configs
    FOR UPDATE USING (auth.uid() = client_id);

-- Leads policies
CREATE POLICY "Clients can view own leads" ON leads
    FOR SELECT USING (auth.uid() = client_id);
CREATE POLICY "Clients can insert own leads" ON leads
    FOR INSERT WITH CHECK (auth.uid() = client_id);
CREATE POLICY "Clients can update own leads" ON leads
    FOR UPDATE USING (auth.uid() = client_id);

-- Conversations policies
CREATE POLICY "Clients can view own conversations" ON conversations
    FOR SELECT USING (auth.uid() = client_id);
CREATE POLICY "Clients can insert own conversations" ON conversations
    FOR INSERT WITH CHECK (auth.uid() = client_id);
CREATE POLICY "Clients can update own conversations" ON conversations
    FOR UPDATE USING (auth.uid() = client_id);

-- Messages policies
CREATE POLICY "Clients can view own messages" ON messages
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM conversations
            WHERE conversations.id = messages.conversation_id
            AND conversations.client_id = auth.uid()
        )
    );
CREATE POLICY "Clients can insert own messages" ON messages
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM conversations
            WHERE conversations.id = messages.conversation_id
            AND conversations.client_id = auth.uid()
        )
    );

-- Events policies
CREATE POLICY "Clients can view own events" ON events
    FOR SELECT USING (auth.uid() = client_id);
CREATE POLICY "Clients can insert own events" ON events
    FOR INSERT WITH CHECK (auth.uid() = client_id);

