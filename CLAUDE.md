# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Activate the virtualenv first — all commands below assume it is active
source venv/bin/activate

# Run the server (port 5000, hot reload)
python run.py

# Seed the PostgreSQL knowledge base (run once, or after clearing the table)
python load_knowledge.py

# Run import/unit tests (no test framework — use inline python3 -c scripts)
python3 -c "from app.services.websocket import handle_stream; print('OK')"
```

The server requires a running PostgreSQL instance on the port in `.env` and a live ngrok tunnel whose public URL is set as `BASE_URL` in `.env`. Twilio webhooks must point to `{BASE_URL}/voice`.

## Architecture

This is a **real-time voice ordering agent** for Butter and Batter Bakery. Incoming phone calls are handled entirely through a single persistent WebSocket per call — no new connections are created mid-conversation.

### Call flow

```
Twilio call → POST /voice
  → plays greeting WAV via <Play>
  → opens WebSocket <Connect><Stream> → /stream/{call_sid}
      → Deepgram Live STT (nova-2, mulaw 8kHz, en-IN)
          on_transcript  → buffers final transcript fragments
          on_utterance_end → joins buffer → process_transcript()
              → search_knowledge_base() (pgvector cosine similarity)
              → get_llm_response() (GPT-4o + RAG context injected into system prompt)
              → text_to_speech_mulaw_bytes() (Deepgram Aura TTS → raw mulaw)
              → send_audio_to_caller() (chunked media events over same WebSocket)
              → await Twilio mark echo (accurate playback completion)
              → schedule_inactivity() (30s timer, per-call)
      on ORDER_COMPLETE → extract_order_details() (GPT-4o) → save_order() (PostgreSQL)
                        → play confirmation → end_call() (Twilio REST hangup)
```

### Active code vs legacy

The **active implementation** lives entirely in `app/`. The root-level `app.py`, `main.py`, and `deepgram_app.py` are earlier Flask/Whisper prototypes — ignore them. `app/routes/process.py` is also a legacy route (record-then-transcribe pattern, replaced by live streaming) but is still registered.

### Key files

| File | Role |
|------|------|
| `app/routes/voice.py` | Entry point for Twilio webhook; plays greeting; opens the WebSocket stream; owns `conversation_store` |
| `app/routes/stream.py` | WebSocket endpoint `/stream/{call_sid}` — delegates to `handle_stream` |
| `app/services/websocket.py` | Core conversation loop: Deepgram STT, inactivity timers, LLM call, TTS, bidirectional audio send, state cleanup |
| `app/services/llm.py` | GPT-4o chat; RAG context injection; `extract_order_details` |
| `app/services/tts.py` | `text_to_speech()` (WAV file, for greeting only) · `text_to_speech_mulaw_bytes()` (raw mulaw, for WebSocket replies) |
| `app/services/rag.py` | OpenAI embedding → pgvector cosine search over `knowledge_base` table |
| `app/services/emotion.py` | `detect_emotion()` (GPT-4o-mini classifier) · `apply_emotion()` returns plain text — Deepgram Aura does not support SSML |
| `load_knowledge.py` | One-shot script to seed `knowledge_base` table with menu, FAQs, policies |

### Per-call state (all in `app/services/websocket.py`)

Every piece of mutable state is a `dict` keyed by `call_sid`. Nothing is shared between calls:

- `active_websockets`, `stream_sids` — the live WebSocket and Twilio streamSid
- `event_loops` — each call stores its own loop reference (fixes multi-call race condition)
- `inactivity_timers`, `inactivity_counts` — 30s silence → prompt; 60s → hangup
- `is_ai_speaking` — suppresses STT transcript processing while audio is playing
- `is_processing` — prevents concurrent LLM calls for the same call
- `mark_events` — `asyncio.Event` per Twilio mark, used to await actual playback completion
- `_cleanup_state(call_sid)` — called on WebSocket close; cancels timers and unblocks all pending mark events

### Database

PostgreSQL on port from `.env` (default 5433). Two tables:
- `orders` — one row per completed order
- `knowledge_base` — pgvector embeddings (1536-dim, `text-embedding-3-small`); queried with `<->` (cosine distance), top-20 results injected into every LLM turn

### Audio format contract

- Twilio → server: mulaw, 8kHz, mono (set by `LiveOptions` encoding)
- Server → Twilio (WebSocket media events): raw mulaw, 8kHz, no WAV header, base64-encoded in 320-byte chunks
- Server → Twilio (initial greeting): linear16 WAV file served over HTTPS via `<Play>`
- `static/` directory is mounted at `/` by FastAPI and serves greeting WAV files; files are deleted after 60s by a background thread
