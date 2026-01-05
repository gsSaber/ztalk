# -*- coding: utf-8 -*-
import uuid

from fastapi import WebSocket

from logger import logger

from .event_bus import EventBus
from .asr_manager import ASRManager
from .tts_manager import TTSManager
from .input_gateway import InputGateway
from .pipeline import SimplePipeline
from .output_gateway import OutputGateway

class Service:
    """简化的对话服务"""

    def __init__(self, websocket: WebSocket, pipeline: SimplePipeline):
        """
        初始化对话服务

        Args:
            websocket: WebSocket连接
            pipeline: 处理管道
        """
        self.pipeline = pipeline
        self.event_bus = EventBus(max_history=100)
        self.asr_manager = ASRManager(self.event_bus, pipeline)
        self.tts_manager = TTSManager(self.event_bus, pipeline)
        self.input_gateway = InputGateway(self.event_bus, websocket)
        self.output_gateway = OutputGateway(self.event_bus, websocket)

        logger.info(f"对话服务已初始化")

    async def handle_message_loop(self) -> None:
        """处理消息循环"""
        await self.input_gateway.handle_connection()
        await self.input_gateway.handle_message_loop()

    # async def stop(self) -> None:
    #     """停止服务"""
    #     try:
    #         await self.asr_manager.shutdown()
    #         await self.tts_manager.shutdown()
    #         await self.event_bus.shutdown()

    #     except Exception as e:
    #         logger.error(f"停止服务时发生错误 - 会话: {self.session_id}, 错误: {e}")
