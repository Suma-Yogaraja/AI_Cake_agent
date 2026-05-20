# Butter and Batter Bakery — AI Voice Ordering Agent

A real-time AI phone agent that takes cake orders over a live phone call. Callers speak naturally; the agent transcribes speech in real time, understands the conversation using GPT-4o with a vector knowledge base, generates a spoken reply, and saves confirmed orders to a database — all within a single persistent WebSocket connection.

---

## Architecture

```
Incoming call
     │
     ▼
Twilio POST /voice
     │  plays greeting WAV via <Play>
     │  opens media stream
     ▼
WebSocket /stream/{call_sid}
     │
     ├──► Deepgram Live STT (nova-2, mulaw 8kHz, en-IN)
     │         on_transcript  → buffers final fragments
     │         on_utterance_end → joins buffer → process_transcript()
     │                                │
     │                                ├──► search_knowledge_base()
     │                                │    (pgvector cosine similarity)
     │                                │
     │                                ├──► get_llm_response()
     │                                │    (GPT-4o + RAG context)
     │                                │
     │                                └──► text_to_speech_mulaw_bytes()
     │                                     (Deepgram Aura TTS)
     │                                          │
     ◄─────────────────────────────────────────┘
     chunked mulaw media events over same WebSocket
          │
          ▼
     Twilio mark echo ──► unblocks playback wait
          │
          ▼
     schedule_inactivity() (30s timer, per-call)

on ORDER_COMPLETE:
     extract_order_details() → save_order() → play confirmation → end_call()
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Telephony | Twilio Voice + Media Streams |
| Speech-to-Text | Deepgram Nova-2 (live streaming) |
| Language Model | OpenAI GPT-4o |
| Text-to-Speech | Deepgram Aura (aura-asteria-en) |
| RAG / Embeddings | OpenAI text-embedding-3-small + pgvector |
| Database | PostgreSQL |
| API Framework | FastAPI + uvicorn |
| Containerisation | Docker |

---

## Features

- **Real-time streaming STT** — audio is transcribed as the caller speaks, not after they stop
- **Mark-based playback sync** — waits for Twilio's mark echo to know exactly when audio finishes playing, not a sleep timer
- **Barge-in handling** — speech captured while the AI is talking is queued and processed after it finishes
- **RAG knowledge base** — menu, FAQs, and policies stored as pgvector embeddings, injected into every LLM turn
- **Structured order extraction** — OpenAI structured outputs with a Pydantic model, no string parsing
- **Business hours awareness** — greeting and confirmation message adapts to current time
- **Inactivity detection** — prompts after 30s silence, hangs up gracefully after 60s
- **Twilio request validation** — all `/voice` requests are HMAC-verified before processing
- **Connection pooling** — psycopg2 `ThreadedConnectionPool` shared across concurrent calls
- **Health check** — `GET /health` verifies DB connectivity, wired into Docker `HEALTHCHECK`

---

## Project Structure

```
app/
├── main.py                  # FastAPI app, logging config, health endpoint
├── config.py                # Env var loading and validation at startup
├── routes/
│   ├── voice.py             # POST /voice — Twilio webhook, plays greeting, opens stream
│   └── stream.py            # WS /stream/{call_sid} — delegates to handle_stream
├── services/
│   ├── websocket.py         # Core loop: STT events, inactivity, LLM, TTS, audio send
│   ├── llm.py               # GPT-4o chat + RAG injection + order extraction
│   ├── tts.py               # Deepgram TTS (WAV for greeting, mulaw for WebSocket replies)
│   └── rag.py               # OpenAI embedding → pgvector cosine search
├── db/
│   ├── connection.py        # ThreadedConnectionPool + context manager
│   └── orders.py            # generate_order_id, save_order, spoken_order_id
└── models/
    └── order.py             # OrderDetails Pydantic model (structured output schema)

journey/                     # Archived prototypes showing the evolution
├── layer1_flask_twilio/     # v1 — Flask + Twilio <Gather speech>
├── layer2_fastapi_postgres/ # v2 — FastAPI + local Whisper transcription
└── layer3_deepgram_record/  # v3 — Deepgram prerecorded (record-then-transcribe)

load_knowledge.py            # One-shot script to seed the knowledge base
run.py                       # Dev server entrypoint (uvicorn with reload)
Dockerfile
```

---

## Prerequisites

- Python 3.11+
- PostgreSQL with the [pgvector](https://github.com/pgvector/pgvector) extension
- [ngrok](https://ngrok.com) to expose the local server to Twilio
- API keys for Twilio, OpenAI, and Deepgram

---

## Setup

**1. Clone and install dependencies**

```bash
git clone https://github.com/Suma-Yogaraja/AI_Cake_agent.git
cd AI_Cake_agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**2. Configure environment variables**

```bash
cp .env.example .env
# Edit .env with your API keys and database credentials
```

**3. Set up the database**

```sql
CREATE DATABASE cakedb;
\c cakedb
CREATE EXTENSION vector;

CREATE TABLE knowledge_base (
    id SERIAL PRIMARY KEY,
    content TEXT,
    embedding vector(1536),
    category TEXT
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    order_id TEXT UNIQUE,
    customer_name TEXT,
    cake_flavour TEXT,
    cake_size TEXT,
    cake_message TEXT,
    customer_phone TEXT,
    allergies TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**4. Seed the knowledge base**

```bash
python load_knowledge.py
```

**5. Start ngrok and update `.env`**

```bash
ngrok http 5000
# Copy the https:// URL into BASE_URL in .env
```

**6. Point Twilio at your server**

Set your Twilio phone number's voice webhook to:
```
POST https://your-ngrok-url.ngrok.io/voice
```

**7. Run**

```bash
python run.py
```

---

## Running with Docker

```bash
docker build -t cake-agent .
docker run --env-file .env -p 5000:5000 cake-agent
```

The Docker `HEALTHCHECK` pings `GET /health` every 30 seconds and restarts the container automatically if it fails.

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/voice` | Twilio webhook — entry point for all inbound calls |
| `WS` | `/stream/{call_sid}` | Twilio media stream WebSocket |
| `GET` | `/health` | Returns server and database status |

**Health response**
```json
{
  "status": "ok",
  "database": "ok",
  "timestamp": "2026-05-20T11:42:03.123456+00:00"
}
```

---

## Key Design Decisions

**Single persistent WebSocket per call**
Twilio's media stream API opens one WebSocket for the entire call duration. All audio — inbound from the caller and outbound to the caller — travels over this single connection. This eliminates per-turn connection overhead and keeps latency low.

**Deepgram live streaming over record-then-transcribe**
The earlier prototypes (in `journey/`) used record-then-transcribe, which added 1–3 seconds of latency per turn just waiting for the recording to finish. Live streaming begins transcribing while the caller is still speaking, eliminating that wait entirely.

**Mark events over sleep for playback sync**
After sending audio chunks to Twilio, a mark frame is sent. Twilio echoes it back when the audio actually finishes playing on the caller's end. Using `asyncio.Event` to wait for this echo is precise — sleeping is a guess that either cuts off audio or wastes time.

**RAG cached once per call**
The knowledge base (menu, FAQs, policies) is static within a call. Fetching and embedding on every turn would add ~200ms latency and unnecessary API costs. One fetch at the start of the call is sufficient.

**Structured outputs for order extraction**
Rather than asking GPT-4o to format text a specific way and then parsing it with string splitting, `openai.beta.chat.completions.parse()` with a Pydantic model constrains the model at the token level. The output is guaranteed to match the schema — no silent data loss if the model varies its wording.

---

## Evolution

This project went through three architectures before reaching the current design:

| Version | Approach | Problem |
|---|---|---|
| v1 | Flask + Twilio `<Gather speech>` | Twilio-side STT, no control over accuracy or latency |
| v2 | FastAPI + local Whisper | 4–6s transcription latency per turn, heavy RAM usage |
| v3 | Deepgram prerecorded | Still record-then-transcribe, 1–3s extra latency per turn |
| v4 | **Deepgram live streaming** | Real-time, sub-second transcription |

The archived prototypes in `journey/` preserve each stage.
