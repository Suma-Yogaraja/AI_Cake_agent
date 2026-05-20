import os
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.config import validate_config
from app.routes import voice, stream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

validate_config()

app = FastAPI()

app.include_router(voice.router)
app.include_router(stream.router)

app.mount("/", StaticFiles(directory="static"), name="static")

#app.mount("/", StaticFiles(directory="."), name="static")