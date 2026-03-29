# AI Voice Agent (WIP)

An end-to-end real-time AI voice agent for a cake shop.

## Overview
This project handles live phone calls, understands customer queries, and responds in real time with low latency.

## Stack
- FastAPI (async backend)
- Twilio (voice + call handling)
- Deepgram (real-time speech-to-text + TTS)
- GPT-4o (response generation)
- PostgreSQL + pgvector (RAG / knowledge base)

## Key Features
- Real-time WebSocket audio streaming
- Conversation memory (context-aware responses)
- Retrieval-Augmented Generation (no hallucinations)
- Emotion-aware voice responses
- Silence detection & call handling
- Latency: ~10s → <2s per turn

## Architecture (high-level)
Twilio → WebSocket → Deepgram (STT) → GPT-4o → Deepgram (TTS) → Twilio

## Status
🚧 Work in progress  
Currently building fully bidirectional streaming for more natural conversations.

---
