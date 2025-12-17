# -*- coding: utf-8 -*-
import json
from fastapi import WebSocket
from dataclasses import dataclass
from logger import logger

from .event_bus import EventBus
from .interfaces import EventListenerMixin
from .events import (
    ASRResultPartial,
    ASRResultFinal,
    VerificationResult,
    TTSStarted,
    TTSStopped,
    TTSPaused,
    TTSResponseUpdate,
    TTSResponseFinish,
    ErrorOccurred,
    TTSChunkGenerated,
    TTSPlaybackFinished,
)


@dataclass
class OutputState:
    """各模块交互的状态"""

    tts_active: bool = False  # TTS是否在播放


class OutputGateway(EventListenerMixin):
    """对话服务信号发送器"""

    def __init__(self, event_bus: EventBus, websocket: WebSocket):
        """
        初始化信号发送器

        Args:
            event_bus: 事件总线
            websocket: WebSocket连接
        """
        self.event_bus = event_bus
        self.websocket = websocket

        self._setup_event_listeners()

        self.state = OutputState()

        logger.debug("信号发送器已初始化")

    def _setup_event_listeners(self):
        """设置前端信号发送监听器，将内部事件转换为前端WebSocket信号"""

        # 监听ASR部分结果，发送update_asr信号
        self.event_bus.subscribe(
            ASRResultPartial,
            self._send_update_asr_signal
        )

        # 监听ASR最终结果，发送finish_asr信号
        self.event_bus.subscribe(
            ASRResultFinal,
            self._send_finish_asr_signal
        )

        logger.debug("前端信号监听器已设置")

    async def _send_signal(self, message: dict) -> None:
        """发送WebSocket消息"""
        try:
            await self.websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.error(
                "发送WebSocket消息失败, 错误: %s", e
            )

    async def _send_update_asr_signal(self, event: ASRResultPartial) -> None:
        """发送ASR更新信号到前端"""
        try:
            logger.info(
                "发送ASR部分结果到前, 文本: '%s'",
                event.text,
            )

            await self._send_signal(
                {
                    "action": "update_asr",
                    "data": {
                        "text": event.text,
                        "confidence": getattr(event, "confidence", 0.0),
                        "is_final": getattr(event, "is_final", False),
                    },
                }
            )
        except Exception as e:
            logger.error(
                "发送update_asr信号失败到前端, 错误: %s", e
            )

    async def _send_finish_asr_signal(self, event: ASRResultFinal) -> None:
        """发送ASR完成信号到前端"""
        try:
            logger.info(
                "发送ASR结果到前端, 文本: '%s'", event.text
            )

            await self._send_signal(
                {
                    "action": "finish_asr",
                    "data": {
                        "text": event.text,
                        "confidence": getattr(event, "confidence", 0.0),
                        "is_final": getattr(event, "is_final", True),
                    },
                }
            )
        except Exception as e:
            logger.error(
                "发送finish_asr信号失败到前端, 错误: %s", e
            )

