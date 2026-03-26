import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routes import voice, process
from app.config import validate_config

validate_config()

app = FastAPI()

app.include_router(voice.router)
app.include_router(process.router)

app.mount("/", StaticFiles(directory="."), name="static")