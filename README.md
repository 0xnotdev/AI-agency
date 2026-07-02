# Multi-Tenant Foundation — Lead Response & Reactivation Platform

This is the production-grade SaaS backend foundation for the lead response automation platform.

## Architecture & Multi-Tenancy

The platform is designed to be multi-tenant from day one. Data isolation between clients is structurally enforced at the database level using Postgres **Row-Level Security (RLS)**. 

### RLS Enforcement Flow
1. **Initial Validation**: When a webhook is received, the backend must verify if the `client_id` is real and `active`. Since the backend doesn't know this yet, it uses the **Service Role Key** (which bypasses RLS) for a global check.
2. **Data Ingestion**: Once the `client_id` is validated, the backend mints a short-lived **scoped JWT** containing `{"sub": "<client_id>"}`. The backend then initializes a temporary `supabase-py` client using this JWT.
3. **Execution**: PostgREST receives the request with the JWT, reads the `sub` claim, and natively enforces the RLS policies, ensuring the operation can *only* affect the authenticated client's data.

## Background Task Queue & Security Model

The platform uses a single-container architecture managed by `supervisord`, running both the FastAPI web server and an `arq` Redis background worker. This replaces the previous GCP Cloud Tasks + OIDC HTTP webhook pattern.

**Why this is better:**
- **No HTTP Boundary**: Background tasks (like calling the LLM or sending messages) are executed directly as Python functions within the trusted Docker container by the `arq` worker.
- **Security Simplification**: We no longer expose an authenticated `/internal` webhook endpoint. All OIDC token verification logic was deleted, eliminating a complex attack surface.
- **Reliability**: `supervisord` automatically restarts the web or worker process if they crash (e.g. from an LLM client panic or memory limit), and emits Telegram alerts on fatal crashes.

## Running Locally

1. **Setup Database & Redis**:
   - Run `supabase start` for the local Postgres/PostgREST stack.
   - Run a local Redis instance for the `arq` worker (e.g. `docker run -d -p 6379:6379 redis`).

2. **Setup Environment**:
   - Copy `.env.example` to `.env`.
   - Update `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_JWT_SECRET`, and `REDIS_URL`.

3. **Run Application (Using Supervisord)**:
   - Install dependencies: `pip install -r requirements.txt`
   - Start both web and worker locally: `supervisord -n -c supervisord.conf`
   - Alternatively, you can run them in separate terminals: `uvicorn app.main:app --reload` and `arq worker.WorkerSettings`.

## Testing

Run tests with Pytest:
```bash
pytest -v
```

> **Note**: The RLS isolation test (`tests/test_rls.py`) requires a real Supabase database running on `localhost:54321`. If it cannot connect to the database, the test will gracefully skip itself.

## Task 2: Next Steps

For Task 2, you will need to build the conversation engine on top of this foundation. 

**Wire up next:**
1. **Reactivation Batch Logic**: Query the `leads` table for dead leads and transition them into active `conversations`.
2. **Channel Senders**: Implement WhatsApp/Email senders in `/services`. Ensure you wrap all external HTTP calls in a robust retry/timeout pattern (e.g., using `tenacity` for retries).
3. **LLM Integration**: Process incoming `messages` against the `client_configs` instructions and FAQ using an LLM. 
4. **Idempotency & Auditing**: Continue emitting `events` for every major action (e.g., `message_sent`, `lead_replied`).
