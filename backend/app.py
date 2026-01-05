from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from logger import *
from modules.service import Service
from modules.pipeline import SimplePipeline
from modules.paraformer_local import ParaformerLocal
from langchain_openai import ChatOpenAI
import os
from config import get_config
from modules.edge_tts import EdgeTTS
from modules.llm_manager import SimpleAgent

llm = ChatOpenAI(
    api_key=get_config().llm.api_key,
    base_url=get_config().llm.base_url,
    model=get_config().llm.model
)

def create_app(config_path: Optional[str] = None) -> FastAPI:
    app = FastAPI(title="ZTalk", version="0.1.0")

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        service = Service(ws, SimplePipeline(asr_model=ParaformerLocal(),llm=SimpleAgent(llm), tts_model=EdgeTTS()))
        await service.handle_message_loop()
    return app

app = create_app()