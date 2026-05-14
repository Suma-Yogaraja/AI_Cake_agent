# AI Voice Ordering System

This project is a real-time voice-based ordering system where users can place orders over a phone call. The system processes live audio, understands the conversation using an LLM, extracts structured order details, and stores them in a database.

The goal was to build something closer to a real-world system rather than a simple API demo.

---

## Overview

The system handles the full flow from a phone call to a stored order:

Voice Call → Speech-to-Text → LLM Processing → Data Extraction → Database

It integrates multiple external services and manages real-time communication between them.

---

## Tech Stack

- Python, FastAPI  
- WebSockets (for real-time audio streaming)  
- OpenAI (LLM)  
- Deepgram (speech-to-text)  
- PostgreSQL + pgvector (for storage and retrieval)  
- Twilio (voice calls)

---

## How it works

1. A user calls the system using Twilio  
2. Audio is streamed in real time over WebSockets  
3. Deepgram converts speech to text  
4. The backend sends the text to the LLM for processing  
5. Relevant data (menu, pricing, etc.) is retrieved using pgvector (RAG)  
6. The LLM generates responses grounded in this data  
7. Order details (items, quantity, etc.) are extracted and structured  
8. Final order is stored in PostgreSQL  

---

## Key parts of the system

- Real-time handling of audio streams using WebSockets  
- Integration of multiple external APIs (Twilio, Deepgram, OpenAI)  
- Use of RAG to improve response accuracy and avoid hallucinations  
- Converting unstructured conversations into structured data  

---

## Challenges

**Real-time processing**  
Handling streaming audio and keeping latency low required careful coordination between services.

**Concurrent users**  
The system supports multiple calls at the same time, so session handling and isolation were important.

**Data extraction from conversations**  
Extracting clean, structured order data from natural language input was not always straightforward and required iteration.

**Reducing incorrect AI responses**  
Using retrieval (pgvector) helped ground responses in actual data instead of relying only on prompts.

---

## Possible improvements

- Add better error handling and retries for external APIs  
- Introduce caching to reduce repeated LLM calls  
- Add monitoring/logging for production readiness  
- Load testing and performance tuning  
- Improve extraction accuracy with more validation or fine-tuning  
