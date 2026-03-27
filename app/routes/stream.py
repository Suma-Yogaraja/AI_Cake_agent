from fastapi import APIRouter, WebSocket
from app.services.websocket import handle_stream

router = APIRouter()

@router.websocket("/stream/{call_sid}")
async def stream(websocket: WebSocket, call_sid: str):
    await websocket.accept()
    await handle_stream(websocket, call_sid)