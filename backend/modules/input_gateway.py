from fastapi import WebSocket
from logger import *
from fastapi import WebSocketDisconnect
import json
from .events import EventFactory
from .event_bus import EventBus
from .events import ErrorOccurred, WebSocketMessageReceived

class InputGateway:
    def __init__(self,event_bus: EventBus,websocket:WebSocket):
        self.websocket = websocket
        self.event_bus = event_bus
        self._setup_event_listeners()

    def _setup_event_listeners(self):
        """设置事件监听器"""
        # 监听错误事件
        self.event_bus.subscribe(
            ErrorOccurred,
            self._handle_error_event,
        )
        # 监听WebSocket消息接收事件 - 这是从网关层接收消息的关键
        self.event_bus.subscribe(
            WebSocketMessageReceived,
            self._handle_websocket_message_received,
        )
        logger.debug("InputGateway的事件监听器已设置")
        
    async def _handle_vad_signal(self, message_type: str, message_data: dict) -> None:
        """处理VAD信号, 发布内部事件，供其他模块响应"""
        logger.info(
            "收到VAD信号创建内部事件,类型: %s",
            message_type,
        )

        if message_type == "vad_speech_start":
            vad_event = EventFactory.create_vad_speech_start(
                confidence=message_data.get("confidence", 0.8),
            )
            await self.event_bus.publish(vad_event)
            logger.info("VAD语音开始事件已发布")

        elif message_type == "vad_speech_end":
            vad_event = EventFactory.create_vad_speech_end(
                confidence=message_data.get("confidence", 0.8),
            )
            await self.event_bus.publish(vad_event)
            logger.info("VAD语音结束事件已发布")

            # 发送一个空的最终音频帧事件，通知ASR系统语音片段结束
            final_audio_event = EventFactory.create_audio_frame_received(
                audio_data=b"",  # 空的音频数据
                sample_rate=48000,
                is_final=True,  # 标记为最终音频帧
            )
            await self.event_bus.publish(final_audio_event)
            logger.info("最终音频帧事件已发布")

    async def _handle_error_event(self, event: ErrorOccurred) -> None:
        """处理错误事件"""
        logger.error(
            "处理错误事件, 类型: %s, 消息: %s",
            event.error_type,
            event.error_message,
        )

    async def _handle_websocket_message_received(
        self, event: WebSocketMessageReceived
    ) -> None:
        """处理WebSocket消息接收事件 - 从网关层接收并处理业务逻辑"""
        try:
            message = event.message

            logger.info(
                "收到WebSocket消息,类型: %s",
                type(message).__name__,
            )

            if isinstance(message, str):  # Handle text messages
                try:
                    message_data = json.loads(message)
                    message_type = message_data.get("action") or message_data.get(
                        "type", "unknown"
                    )

                    logger.info(
                        "处理文本信号, 信号: %s",
                        message_type,
                    )

                    if message_type in ["vad_speech_start", "vad_speech_end"]:
                        await self._handle_vad_signal(message_type, message_data)
                    else:
                        logger.warning(
                            "未知的文本信号类型: %s",
                            message_type,
                        )

                except json.JSONDecodeError:
                    logger.warning(
                        "无法解析WebSocket消息: %s",
                        message
                    )

            else:
                logger.warning(
                    "收到未知类型的WebSocket消息"
                )

        except Exception as e:
            logger.error(
                "处理WebSocket消息失败, 错误: %s", e
            )
 
    async def handle_message_loop(self):
        try:
            while True:
                data = await self.websocket.receive()
                await self._process_message(data)
        except WebSocketDisconnect:
            logger.info(f"WebSocket断开")
        except Exception as e:
            logger.error(f"消息处理错误，错误: {e}")

    async def _process_message(self, data):
        try:
            if data["type"] == "websocket.receive":
                if "text" in data:
                    # 文本消息 - 发布WebSocket消息接收事件
                    await self._handle_text_message(data["text"])
                elif "bytes" in data:
                    # 二进制消息（音频数据）- 发布音频帧接收事件
                    await self._handle_audio_message(data["bytes"])

        except Exception as e:
            logger.error(f"消息处理错误{e}")

    async def _handle_text_message(self, text_message: str) -> None:
        try:
            message = json.loads(text_message)
            msg_type = message.get("action") or message.get("type", "unknown")

            logger.debug("收到文本消息,type: %s",  msg_type)

            # 发布WebSocket消息接收事件，让业务层处理具体逻辑
            event = EventFactory.create_websocket_message_received(
                message=text_message
            )
            await self.event_bus.publish(event)
        except json.JSONDecodeError:
            # 如果不是JSON格式，也发布事件让业务层处理
            event = EventFactory.create_websocket_message_received(
                message=text_message
            )
            await self.event_bus.publish(event)

    async def handle_connection(self):
        """
        处理新的WebSocket连接
        """
        try:
            await self.websocket.accept()

            logger.info(f"WebSocket连接已建立")

        except Exception as e:
            logger.error(f"连接处理失败,错误: {e}")

    async def _handle_audio_message(self, audio_data: bytes) -> None:
        """
        处理音频消息 - 只发布事件，不处理具体业务逻辑
        Args:
            audio_data: 音频数据
        """
        # 发布音频帧接收事件，让业务层处理具体逻辑
        event = EventFactory.create_audio_frame_received(
            audio_data=audio_data,
            sample_rate=48000,
            is_final=False,
        )
        await self.event_bus.publish(event)
