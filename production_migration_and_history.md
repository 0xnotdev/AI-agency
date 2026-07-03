# LeadRecover AI: The Complete Engineering History & Production Migration Blueprint

> [!IMPORTANT]
> **Purpose of this Document:**
> This document is the ultimate, exhaustive engineering master file. It is designed to act as a complete neural download for any advanced AI agent or Senior DevOps Engineer taking over this project. It meticulously details the granular code history, every bug fixed, and provides the exact architectural roadmap required to transition this system from its current "Testing Prototype" state into a hardened, enterprise-grade Production environment.

---

## PART I: GRANULAR DEVELOPMENT HISTORY & CODEBASE STATE

### 1. The Core Infrastructure (`app/main.py`)
We established the FastAPI entry point, handling global exception routing and background task delegation.
- **Initial State:** Built basic endpoints for webhooks.
- **Testing Interface:** Created `/chat` (The Web Tester) which simulates incoming Meta webhooks by generating identical JSON payloads and posting them to `/api/test-webhook`, which then forwards them to `/webhooks/whatsapp`.
- **Global Error Handling:** Implemented a global `Exception` catcher returning strict 500 JSON payloads to prevent server death on malformed inputs.

### 2. The Multi-Tenant Supabase Schema
The entire application relies on Supabase for strict data segregation.
- `clients`: The top-level entity representing the agency's customers.
- `client_configs`: Stores `client_id`, `whatsapp_phone_number_id`, `whatsapp_access_token`, `google_calendar_tokens` (JSONB), and `system_prompt` parameters.
- `leads`: Stores `id`, `phone`, `name`. Unique per phone number.
- `conversations`: Links `client_id` and `lead_id`.
- `messages`: Stores `conversation_id`, `content`, `direction` (inbound/outbound), and `created_at`.
- `errors`: A logging table for webhook failures.

### 3. The Conversational Engine (`app/services/conversation.py`)
This is the central nervous system.
- **Webhook Interception:** Meta hits `/webhooks/whatsapp`. The backend extracts `phone_number_id` and `from` (lead's phone).
- **Background Dispatch:** `process_inbound_message.delay(conversation_id, message_id)` is dispatched so Meta receives a 200 OK instantly, preventing webhook timeouts and retries.
- **The Execution Loop:**
  1. Fetches `client_config` based on `whatsapp_phone_number_id`.
  2. Fetches the last 20 messages from the `messages` table for context.
  3. Invokes `generate_reply` in `llm.py`.
  4. Inserts the LLM's response into the `messages` table.
  5. Triggers `send_whatsapp_message` to dispatch the response back to the lead.

### 4. The LLM & Tool Calling Orchestration (`app/services/llm.py`)
This is where the deepest engineering challenges occurred. We used OpenRouter (GPT-4o-mini) with function calling.

#### Challenge A: The Temporal Hallucination
- **The Bug:** The LLM had no concept of "today" and generated calendar dates from 2023.
- **The Code Fix:** Injected a dynamic UTC timestamp into the system prompt:
  ```python
  current_datetime = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
  system_prompt += f"\n\nCRITICAL INSTRUCTION: The current date and time is {current_datetime} (UTC). When booking or checking availability, strictly use dates based on this current time."
  ```

#### Challenge B: The Silent Apology Loop
- **The Bug:** If the user typed "monday 1 pm ist", the LLM would occasionally fail to convert it to ISO-8601 and pass the literal string to the tool. The tool would crash, Python would catch the exception, and the LLM would output a generic "I apologize..." text. Once this apology was saved to the DB, the LLM got trapped in a historical loop of failure.
- **The Code Fix:** We engineered an aggressive self-correction prompt passed back to the LLM during the tool execution phase:
  ```python
  except Exception as e:
      logger.error(f"Error checking calendar: {str(e)}", exc_info=True)
      result = f"System Error: The tool failed to execute. You likely provided an invalid date format. You MUST provide strict ISO-8601 timestamps (e.g. 2026-07-06T13:00:00+00:00). Please call the tool again with the correct format."
  ```
  This allowed the LLM to realize its mistake and successfully call the tool a second time *in the same generation loop*.

#### Challenge C: The Meta Webhook Delivery Bug (Silent Failures)
- **The Bug:** After rotating the Meta API token, real webhooks from Meta stopped reaching the server entirely, even though the Web Tester UI worked perfectly. The Meta dashboard showed the webhook as "subscribed", but the backend API confirmed the app was not actually attached to the WhatsApp Business Account (WABA).
- **The Fix:** We manually bypassed the Meta UI bugs by executing a forced POST request to the Graph API (`/v20.0/{waba_id}/subscribed_apps`) using the valid token. This successfully registered the app to the WABA and restored inbound webhook delivery.

### 5. The Google Calendar Integration (`app/services/calendar.py`)
- **OAuth Management:** Implemented `_get_valid_credentials()` to read the JSONB tokens from Supabase and automatically refresh them using the `refresh_token` if they expired.
- **The Parsing Crash:** `datetime.fromisoformat` was too rigid and crashed on minor LLM formatting errors. We replaced it with `dateutil.parser.parse()`.
- **The 400 Zero-Window Fix:** If the LLM passed `start_time == end_time`, Google rejected the API call. We added logic to dynamically extend the window by 4 hours if `dt_end <= dt_start`.
- **Slot Calculation:** The `check_availability` function pulls the `busy` arrays from Google, iterates through the requested time window in 30-minute increments, and returns an array of strictly available slots to the LLM.

---

## PART II: THE ROADMAP TO PRODUCTION (PHASE 4)

The system currently relies on temporary Meta tokens, manual DB edits, and simple background tasks. To transition to a **Hardened Production Environment** capable of onboarding 100+ clients, the following structural migrations MUST be executed.

### 1. Permanent Meta/WhatsApp Integration (Escaping the 24-Hour Token)
- **Current State:** The system uses the Meta Developer temporary access token which expires every 24 hours, causing `401 Unauthorized` errors in production.
- **Production Requirement:**
  - Create a permanent System User in the Meta Business Manager.
  - Generate a permanent Access Token.
  - Submit the Meta App for App Review (requires Business Verification, Privacy Policy, and a Terms of Service page).
  - Subscribe the Webhook to the `messages` field at the app level, not just the test number level.

### 2. Scalable Message Queueing (Replacing `BackgroundTasks`)
- **Current State:** FastAPI's internal `BackgroundTasks` are stored in RAM. If the Railway container restarts or crashes, pending messages are lost forever.
- **Production Requirement:**
  - Implement **Celery + Redis** (or a lightweight alternative like **ARQ** for asyncio).
  - When Meta sends a webhook, it is immediately dumped into a Redis queue.
  - Dedicated worker dynos pull from the queue, allowing horizontal scaling (adding more workers if 5,000 leads text at once).
  - Implement Dead Letter Queues (DLQ) for failed messages (e.g., if OpenAI's API goes down, the message stays in the queue and retries 5 minutes later).

### 3. Multi-Tenant Google OAuth Flow
- **Current State:** Google tokens were manually extracted and injected into the Supabase database.
- **Production Requirement:**
  - Build a React/Next.js Frontend Dashboard.
  - Implement the standard Google OAuth2 flow (`/auth/google/login` -> `/auth/google/callback`).
  - Upon callback, the backend exchanges the authorization code for the `access_token` and `refresh_token` and securely saves them to `client_configs` linked to the logged-in user.

### 4. Database Hardening & Row Level Security (RLS)
- **Current State:** Supabase is accessible via a backend service key, meaning all data is pooled.
- **Production Requirement:**
  - Enable Row Level Security (RLS) policies on all tables in Supabase.
  - `leads`, `conversations`, and `messages` must be strictly restricted to `auth.uid() == client_id`.
  - Add PostgreSQL indexes on `whatsapp_phone_number_id` (in `client_configs`) and `phone` (in `leads`) to prevent slow sequential scans as the database grows to millions of rows.

### 5. Outbound Database Reactivation (DBR) Drip Engine
- **Current State:** The system only responds to inbound messages.
- **Production Requirement:**
  - Create an endpoint to upload CSVs of dormant leads.
  - Build a Cron Scheduler (using Celery Beat) to drip messages to these leads at a rate of 50-100 per day.
  - Meta bans numbers that send 1,000 templates instantly. The DBR engine must queue messages with jitter (random delays between 5 and 15 minutes) to mimic human outreach and protect phone number reputation.

### 6. Observability, Logging, and Analytics
- **Current State:** Errors are logged to a Supabase `errors` table or Railway's console.
- **Production Requirement:**
  - Integrate **Sentry** for real-time error tracking and stack trace capturing.
  - Integrate **Datadog** or **PostHog** to track conversion metrics (e.g., "Inbound Message Received" -> "Tool Called" -> "Meeting Booked").
  - Provide an Analytics Dashboard to the agency client showing exactly how much revenue the AI recovered.

### 7. Stripe / Payment Infrastructure
- **Current State:** No billing system.
- **Production Requirement:**
  - Integrate Stripe Billing (or Xflow/Skydo for Indian compliance).
  - The client must enter a credit card to activate the AI agent.
  - The system automatically bills the $500/month infrastructure retainer, and automatically suspends the WhatsApp webhook connection if the payment fails.

---

## Conclusion: The Path Forward
To move from testing to production, an AI Agent must first tackle **Item #2 (Redis/Celery Queues)** for stability, followed by **Item #1 (Permanent Meta Tokens)**, and **Item #3 (Google OAuth UI)**. Once these three pillars are established, the system transitions from a high-functioning prototype into a fully monetizable SaaS product.
