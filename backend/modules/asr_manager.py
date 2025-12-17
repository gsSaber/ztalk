# -*- coding: utf-8 -*-
import asyncio
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional
from collections import deque
import numpy as np
import re

from logger import logger

from .events import EventFactory
from .event_bus import EventBus

from .events import (
    AudioFrameReceived,
    VADSpeechStart,
    VADSpeechEnd,
    TTSResponseUpdate,
)
from .interfaces import Manager
from .pipeline import SimplePipeline

@dataclass
class ConsumerState:
    """消费者状态"""

    running: bool = False
    processing: bool = False
    last_activity: float = 0.0
    processed_chunks: int = 0
    errors: int = 0


class ASRManager:
    """事件驱动的ASR管理器"""

    def __init__(self, event_bus: EventBus, pipeline: SimplePipeline):
        """
        初始化ASR管理器

        Args:
            event_bus: 事件总线
            pipeline: 处理管道
        """
        self.event_bus = event_bus
        self.pipeline = pipeline

        # ASR状态
        self.accumulated_text = ""
        self.confidence_sum = 0.0
        self.chunk_count = 0
        self.asr_cache = {}  # ASR流式识别缓存

        # 音频缓冲区 - 优化版本，减少数据复制
        self.audio_buffer = deque(maxlen=1000)  # 最多保存1000个音频块
        self.buffer_lock = asyncio.Lock()

        # 流式ASR相关参数 - 参考Stream类的实现
        self.asr_model = self.pipeline.get_asr_model()
        self.chunk_bytes = None
        if hasattr(self.asr_model, "chunk_secs") and self.asr_model.chunk_secs:
            # 计算chunk字节数：chunk_secs * 采样率 * 2(16位)
            sample_rate = getattr(self.asr_model, "TARGET_SAMPLE_RATE", 16000)
            self.chunk_bytes = int(self.asr_model.chunk_secs * sample_rate * 2)
            logger.info(
                "ASR chunk字节数: %d (%.2f秒)",
                self.chunk_bytes,
                self.asr_model.chunk_secs,
            )

        # 音频保存状态
        self.is_recording = False  # 是否正在录音
        self.recording_start_time = None  # 录音开始时间
        self.recording_buffer = []  # 录音缓冲区

        # 消费者状态
        self.consumer_state = ConsumerState()
        self.consumer_task: Optional[asyncio.Task] = None

        # 验证任务
        self.verification_delay = 1.0
        self.verification_task: Optional[asyncio.Task] = None

        # 设置事件监听器
        self._setup_event_listeners()

        logger.info("ASR管理器已初始化")

    def _setup_event_listeners(self):
        """设置事件监听器"""
        # 音频帧接收事件
        self.event_bus.subscribe(
            AudioFrameReceived,
            self._handle_audio_frame,
        )

        # VAD开始事件
        self.event_bus.subscribe(
            VADSpeechStart,
            self._handle_vad_speech_start,
        )

        # VAD结束事件
        self.event_bus.subscribe(
            VADSpeechEnd,
            self._handle_vad_speech_end,
        )

    async def _handle_audio_frame(self, event: AudioFrameReceived) -> None:
        """处理音频帧事件"""
        # 添加音频数据到缓冲区
        async with self.buffer_lock:
            self.audio_buffer.append(
                {
                    "data": event.audio_data,
                    "timestamp": time.time(),
                    "sample_rate": getattr(event, "sample_rate", 16000),
                    "is_final": getattr(event, "is_final", False),
                }
            )
            
        logger.debug(
            "音频帧已加入缓冲区 大小: %d",
            len(event.audio_data),
        )

        # 如果正在录音，累积音频数据
        if self.is_recording:
            self.recording_buffer.append(event.audio_data)
    
    async def _start_asr_processing(self) -> None:
        """启动ASR处理"""
        logger.info("启动ASR处理")

        # 重置ASR状态
        await self._reset_asr()

        # 启动消费者
        await self._start_consumer()

    async def _handle_vad_speech_start(self, event) -> None:
        """处理VAD语音开始事件"""
        logger.info("VAD语音开始 启动ASR处理")
        # 启动ASR处理
        await self._start_asr_processing()

    async def _handle_vad_speech_end(self, event) -> None:
        """处理VAD语音结束事件"""
        logger.info("VAD语音结束 ASR处理剩余音频")

        # 取消正在进行的验证任务
        if self.verification_task and not self.verification_task.done():
            self.verification_task.cancel()
            try:
                await self.verification_task
            except asyncio.CancelledError:
                logger.debug("VAD语音结束时取消验证任务")

        await self._stop_consumer()
        await self._finish_asr_processing()

    async def _finish_asr_processing(self) -> None:
        """完成ASR处理"""
        # 计算最终置信度
        final_confidence = self.confidence_sum / max(self.chunk_count, 1)
        final_text = self.accumulated_text.strip()
        await self._publish_asr_result(final_text, True, final_confidence)
        logger.info("ASR处理已完成, 结果: %s", final_text)

    async def _start_consumer(self) -> None:
        """启动音频消费者"""
        if self.consumer_task and not self.consumer_task.done():
            return

        self.consumer_state.running = True
        self.consumer_task = asyncio.create_task(self._asr_consumer())

        logger.info("ASR消费者已启动")

    async def _stop_consumer(self) -> None:
        """停止音频消费者"""
        self.consumer_state.running = False

        if self.consumer_task and not self.consumer_task.done():
            self.consumer_task.cancel()
            try:
                await self.consumer_task
            except asyncio.CancelledError:
                pass

        self.consumer_task = None

    async def _asr_consumer(self) -> None:
        """ASR音频消费者"""
        logger.info("ASR消费者开始运行")

        accumulated_audio = bytearray()
        processed_bytes = 0
        last_metadata = {}  # 保存最后一个音频块的元数据

        try:
            while self.consumer_state.running:
                # 检查缓冲区是否有数据
                audio_chunk = None
                async with self.buffer_lock:
                    if self.audio_buffer:
                        audio_chunk = self.audio_buffer.popleft()

                if audio_chunk:
                    # 直接累积音频数据，减少数据复制
                    chunk_data = audio_chunk["data"]
                    accumulated_audio.extend(chunk_data)

                    # 保存元数据（只需要最后一个的）
                    last_metadata = {
                        "timestamp": audio_chunk["timestamp"],
                        "sample_rate": audio_chunk["sample_rate"],
                        "is_final": audio_chunk.get("is_final", False),
                    }

                    is_final = last_metadata["is_final"]

                    logger.debug(
                        "ASR消费者处理音频块, 块大小: %d, 累积字节: %d",
                        len(chunk_data),
                        len(accumulated_audio),
                    )

                    # 检查是否需要处理累积的数据
                    should_process = False

                    if is_final:
                        # 遇到final情况，立即处理
                        should_process = True
                        logger.debug(
                            "ASR遇到final音频块，立即处理累积数据, 累积字节: %d",
                            len(accumulated_audio),
                        )
                    elif (
                        self.chunk_bytes
                        and len(accumulated_audio) - processed_bytes >= self.chunk_bytes
                    ):
                        # 累积到足够的字节数
                        should_process = True
                        logger.debug(
                            "ASR累积到足够字节数，开始处理, 累积字节: %d, chunk字节: %d",
                            len(accumulated_audio),
                            self.chunk_bytes,
                        )

                    if should_process and len(accumulated_audio) > processed_bytes:
                        # 处理累积的音频数据
                        await self._process_accumulated_audio(
                            accumulated_audio, processed_bytes, is_final, last_metadata
                        )
                        self.consumer_state.last_activity = time.time()
                        self.consumer_state.processed_chunks += 1

                        # 更新已处理的字节数
                        if is_final:
                            processed_bytes = len(accumulated_audio)
                        else:
                            processed_bytes = len(accumulated_audio) - (
                                len(accumulated_audio) % self.chunk_bytes
                            )# type:ignore
                else:
                    # 没有数据，短暂等待
                    await asyncio.sleep(0.005)  # 5ms，减少等待时间

        except asyncio.CancelledError:
            logger.debug("ASR消费者被取消")
        except Exception as e:
            logger.error("ASR消费者异常错误: %s", e)
            self.consumer_state.errors += 1

            # 发布错误事件
            error_event = EventFactory.create_error(
                error_type="asr_consumer_error",
                error_message=str(e),
                component="ASRManager",
            )
            await self.event_bus.publish(error_event)
        finally:
            # 处理剩余的累积数据
            if len(accumulated_audio) > processed_bytes:
                logger.debug(
                    "ASR处理剩余的累积音频数据,剩余字节: %d",
                    len(accumulated_audio) - processed_bytes,
                )
                try:
                    await self._process_accumulated_audio(
                        accumulated_audio, processed_bytes, True, last_metadata
                    )
                except Exception as e:
                    logger.error(
                        "ASR处理剩余累积音频数据失败,错误: %s",
                        e,
                    )

            self.consumer_state.processing = False
            logger.info("ASR消费者已停止")

    async def _process_accumulated_audio(
        self,
        accumulated_audio: bytearray,
        processed_bytes: int,
        is_final: bool,
        metadata: dict,
    ) -> None:
        """
        处理累积的音频数据 - 优化版本

        Args:
            accumulated_audio: 累积的音频字节数据
            processed_bytes: 已处理的字节数
            is_final: 是否为最终处理
            metadata: 音频元数据（timestamp, sample_rate等）
        """
        try:
            self.consumer_state.processing = True

            # 提取需要处理的音频数据
            audio_data = bytes(accumulated_audio[processed_bytes:])

            # 检查音频数据是否为空
            if not audio_data or len(audio_data) == 0:
                logger.debug("音频数据为空，跳过ASR处理")
                return

            # 检查是否有ASR模型
            if not self.asr_model:
                logger.warning("无ASR模型，跳过ASR处理")
                return

            # 转换音频格式
            audio_float = self._pcm_to_float(audio_data)

            # 获取ASR模型的目标采样率
            target_sample_rate = getattr(self.asr_model, "TARGET_SAMPLE_RATE", 16000)
            logger.debug(
                "ASR模型的目标采样率: %d",
                target_sample_rate,
            )

            # TODO: adapt to more ASR models
            new_text = ""
            chunks = self.asr_model.get_chunks(audio_float, target_sample_rate)

            for chunk in chunks:
                # 使用asr_cache，确保缓存状态正确
                chunk_text = self.asr_model.recognize_stream(
                    chunk, self.asr_cache, is_final=is_final
                )
                if chunk_text:
                    new_text += chunk_text
                    logger.debug(
                        "ASR识别到新文本: %s", chunk_text
                    )

            # 如果是最终结果，清空缓存
            if is_final:
                self.asr_cache = {}
                logger.debug("ASR缓存已清空")

            # 处理识别结果
            if new_text:
                logger.info(
                    "ASR识别到新文本: '%s'", new_text
                )

                # 累积文本
                self.accumulated_text += new_text
                # 模拟置信度（实际应该从ASR模型获取）
                mock_confidence = 0.85
                self.confidence_sum += mock_confidence
                self.chunk_count += 1

                # 发布部分ASR结果事件
                await self._publish_asr_result(
                    self.accumulated_text, False, mock_confidence
                )
            else:
                logger.debug("ASR未识别到新文本")

        except Exception as e:
            logger.error(
                "ASR处理累积音频数据失败，错误: %s", e
            )
            raise
        finally:
            self.consumer_state.processing = False

    def _pcm_to_float(self, pcm: bytes) -> np.ndarray:
        """
        将PCM字节数据转换为float numpy数组

        Args:
            pcm: PCM字节数据

        Returns:
            np.ndarray: float音频数据数组
        """
        pcm_int16 = np.frombuffer(pcm, dtype=np.int16)
        return pcm_int16.astype(np.float32) / 32768.0

    async def _publish_asr_result(
        self, text: str, is_final: bool, confidence: float
    ) -> None:
        """
        发布ASR结果事件

        Args:
            text: 识别文本
            is_final: 是否为最终结果
            confidence: 置信度
        """
        event = EventFactory.create_asr_result(
            text=text,
            is_final=is_final,
            confidence=confidence,
        )
        await self.event_bus.publish(event)

        logger.info(
            "ASR结果已发布,文本: %s, 最终: %s",
            text,
            is_final,
        )

    async def _reset_asr(self) -> None:
        logger.debug("完全重置ASR状态")

        # 停止消费者
        await self._stop_consumer()

        # 重置所有状态变量
        self.accumulated_text = ""
        self.confidence_sum = 0.0
        self.chunk_count = 0
        self.asr_cache = {}  # 重置ASR缓存

        # 完全重置消费者状态
        self.consumer_state = ConsumerState()

        # 清空音频缓冲区
        async with self.buffer_lock:
            self.audio_buffer.clear()

        logger.info("ASR状态已完全重置")

    async def shutdown(self) -> None:
        """关闭ASR管理器"""
        logger.info("关闭ASR管理器")

        # 停用ASR
        await self._reset_asr()

        logger.info("ASR管理器已关闭")
