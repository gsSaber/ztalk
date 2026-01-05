# -*- coding: utf-8 -*-
import asyncio
import time
from dataclasses import dataclass
from typing import Optional, NamedTuple

from logger import logger

from .events import EventFactory
from .event_bus import EventBus
from .events import (
    ASRResultFinal,
    VerificationResult,
    TTSPlaybackFinished,
    VADSpeechStart,
)
from .interfaces import Manager


class TTSQueueItem(NamedTuple):
    """TTS队列项的数据结构"""

    task_id: int
    audio_chunk: bytes
    resp_text: str
    is_final: bool


@dataclass
class ConsumerState:
    """消费者状态"""

    running: bool = False
    processing: bool = False
    last_activity: float = 0.0
    processed_tasks: int = 0
    errors: int = 0


class TTSManager(Manager):
    """事件驱动的TTS管理器"""

    def __init__(self, event_bus: EventBus, pipeline):
        """
        初始化TTS管理器

        Args:
            event_bus: 事件总线
            pipeline: 处理管道
        """
        self.event_bus = event_bus
        self.pipeline = pipeline

        # TTS状态
        self.is_paused = False  # 暂停状态
        self.current_task_id = 0
        self.current_text = ""  # 当前TTS文本
        self.accumulated_text = ""  # 累积的TTS文本
        self.asr_text = ""  # ASR识别的文本
        self.tts_gen_task: Optional[asyncio.Task] = None

        # TTS音频队列（用于音频流处理）
        self.tts_queue = asyncio.Queue()

        # 消费者状态
        self.consumer_state = ConsumerState()
        self.consumer_task: Optional[asyncio.Task] = None

        # 设置事件监听器
        self._setup_event_listeners()

        logger.info("TTS管理器已初始化")

    def _setup_event_listeners(self):
        """设置事件监听器"""

        self.event_bus.subscribe(
            ASRResultFinal,
            self._handle_asr_result_final,
        )

        # 监听TTS播放完成事件
        self.event_bus.subscribe(
            TTSPlaybackFinished,
            self._handle_tts_playback_finished,
        )

        # 监听VAD语音开始事件
        self.event_bus.subscribe(
            VADSpeechStart,
            self._handle_vad_speech_start,
        )

    async def _handle_asr_result_final(self, event: ASRResultFinal) -> None:
        """处理ASR最终结果事件"""
        # 保存ASR结果文本
        await self.reset_tts()
        self.asr_text = event.text

        # 生成新的任务ID
        task_id = self._generate_task_id()

        logger.info(
            "TTS管理器收到ASR最终结果, 文本: %s",
            self.asr_text,
        )

        # 异步启动TTS生成，不等待完成
        if self.tts_gen_task and not self.tts_gen_task.done():
            self.tts_gen_task.cancel()
            try:
                await self.tts_gen_task
            except asyncio.CancelledError:
                pass
        self.tts_gen_task = asyncio.create_task(
            self.generate_tts_from_text(self.asr_text)
        )
        await self._start_consumer()

    async def reset_tts(self) -> None:
        """重置TTS状态 - 完全清理并重置所有状态"""
        logger.debug("重置TTS状态,调用栈: %s", "reset_tts")

        # 重置所有状态变量
        self.is_paused = False  # 清除暂停状态
        self.current_text = ""  # 重置当前文本
        self.accumulated_text = ""  # 重置累积文本
        self.asr_text = ""  # 重置ASR文本

        # 取消TTS生成任务
        if self.tts_gen_task and not self.tts_gen_task.done():
            self.tts_gen_task.cancel()
            try:
                await self.tts_gen_task
            except asyncio.CancelledError:
                pass
            self.tts_gen_task = None

        # 停止消费者
        await self._stop_consumer()

        # 清空TTS音频队列
        while not self.tts_queue.empty():
            try:
                self.tts_queue.get_nowait()
                self.tts_queue.task_done()
            except asyncio.QueueEmpty:
                break

        self.consumer_state = type(self.consumer_state)()

        if self.consumer_task and not self.consumer_task.done():
            self.consumer_task.cancel()
            try:
                await self.consumer_task
            except asyncio.CancelledError:
                pass
            self.consumer_task = None

        logger.info("TTS状态已完全重置")

    async def _start_consumer(self) -> None:
        """启动TTS消费者"""
        if self.consumer_task and not self.consumer_task.done():
            return

        self.consumer_state.running = True
        self.consumer_task = asyncio.create_task(self._tts_consumer())

        logger.info("TTS消费者已启动")

    async def _stop_consumer(self) -> None:
        """停止TTS消费者"""
        self.consumer_state.running = False

        if self.consumer_task and not self.consumer_task.done():
            self.consumer_task.cancel()
            try:
                await self.consumer_task
            except asyncio.CancelledError:
                pass

        self.consumer_task = None
        logger.info("TTS消费者已停止")

    async def _pause_tts(self) -> None:
        """暂停TTS - 停止消费但保留队列"""
        logger.debug(
            "尝试暂停TTS,当前暂停状态: %s", self.is_paused
        )

        if self.is_paused:
            logger.debug(
                "TTS已经处于暂停状态，无需重复暂停"
            )
            return

        self.is_paused = True
        logger.info("TTS已暂停")

    async def _resume_tts(self) -> None:
        """恢复TTS - 重新开始消费队列"""
        logger.debug(
            "尝试恢复TTS,当前暂停状态: %s", self.is_paused
        )

        if not self.is_paused:
            logger.debug("TTS未处于暂停状态，无需恢复")
            return

        self.is_paused = False
        logger.info("TTS已恢复")

    async def _tts_consumer(self) -> None:
        """TTS音频消费者"""
        logger.debug("TTS消费者开始运行")
        last_sent_text = ""  # 记录上次发送的文本，避免重复发送

        try:
            while self.consumer_state.running:
                # 检查是否处于暂停状态
                if self.is_paused:
                    # 暂停状态下不消费音频，等待恢复
                    await asyncio.sleep(0.05)  # 50ms
                    continue

                try:
                    # 从TTS音频队列获取音频项
                    item = await asyncio.wait_for(self.tts_queue.get(), timeout=0.1)

                    if item is None:
                        logger.debug("收到停止信号，TTS消费者退出")
                        break

                    if item.task_id != self.current_task_id:
                        logger.debug(
                            "跳过旧任务的数据，任务ID: %s, 当前ID: %s",
                            item.task_id,
                            self.current_task_id,
                        )
                        self.tts_queue.task_done()
                        continue

                    # 发送音频数据（如果有的话）
                    if item.audio_chunk:
                        try:
                            # 改为通过事件总线发送，由前端监听并发送
                            event = EventFactory.create_tts_chunk_generated(
                                audio_chunk=item.audio_chunk,
                                task_id=item.task_id,
                                text=item.resp_text,
                            )
                            await self.event_bus.publish(event)
                            logger.debug(
                                "发送TTS音频数据事件: %d 字节", len(item.audio_chunk)
                            )
                        except Exception as e:
                            logger.error("发送TTS音频数据事件失败: %s", e)

                    # 只有当文本内容发生变化时才发送
                    if item.resp_text != last_sent_text:
                        await self._publish_tts_update(item.task_id, item.resp_text)
                        logger.debug(
                            "TTS生成更新，发送update_resp信号: %s", item.resp_text
                        )
                        last_sent_text = item.resp_text
                        # 更新当前文本
                        self.current_text = item.resp_text
                        self.accumulated_text += item.resp_text

                    await asyncio.sleep(0)

                    if item.is_final:
                        # 发布TTS完成事件
                        asyncio.create_task(
                            self._publish_tts_finished(item.task_id, item.resp_text)
                        )
                        logger.debug(
                            "TTS生成完成，发送finish_resp信号: %s", item.resp_text
                        )

                    self.tts_queue.task_done()
                    self.consumer_state.last_activity = time.time()
                    self.consumer_state.processed_tasks += 1

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error("TTS消费者处理音频时出错: %s", e)
                    self.consumer_state.errors += 1
                    if not self.tts_queue.empty():
                        self.tts_queue.task_done()

        except asyncio.CancelledError:
            logger.debug("TTS消费者被取消")
        except Exception as e:
            logger.error("TTS消费者异常，错误: %s", e)
            self.consumer_state.errors += 1

            # 发布错误事件
            error_event = EventFactory.create_error(
                error_type="tts_consumer_error",
                error_message=str(e),
                component="TTSManager",
            )
            await self.event_bus.publish(error_event)
        finally:
            self.consumer_state.processing = False
            logger.debug("TTS消费者已停止")

    async def _publish_tts_started(self, text: str, task_id: int) -> None:
        """
        发布TTS开始事件

        Args:
            text: TTS文本
            task_id: 任务ID
        """
        event = EventFactory.create_tts_started(
            text=text, task_id=task_id
        )
        await self.event_bus.publish(event)

        logger.debug(
            "TTS开始事件已发布, 任务ID: %s", task_id
        )

    async def _publish_tts_finished(self, task_id: int, final_text: str) -> None:
        """
        发布TTS完成事件

        Args:
            task_id: 任务ID
            final_text: 最终文本
        """
        event = EventFactory.create_tts_response_finish(
            task_id=task_id, text=final_text
        )
        await self.event_bus.publish(event)

        logger.debug(
            "TTS完成事件已发布, 任务ID: %s",task_id
        )

    async def _publish_tts_update(self, task_id: int, update_text: str) -> None:
        """
        发布TTS更新事件

        Args:
            task_id: 任务ID
            final_text: 最终文本
        """
        event = EventFactory.create_tts_response_update(
            text=update_text, task_id=self.current_task_id
        )
        await self.event_bus.publish(event)

        logger.debug(
            "TTS更新事件已发布，任务ID: %s",task_id
        )

    async def _publish_tts_pause(self, task_id: int, text: str) -> None:
        """
        发布TTS暂停事件

        Args:
            task_id: 任务ID
            text: 当前文本
        """
        event = EventFactory.create_tts_paused(
            text=text, task_id=task_id
        )
        await self.event_bus.publish(event)

        logger.debug(
            "TTS暂停事件已发布，任务ID: %s", task_id
        )

    async def _handle_tts_playback_finished(self, event) -> None:
        """处理TTS播放完成事件"""
        logger.info("TTS播放完成，重置TTS状态")
        await self.reset_tts()

    async def _handle_vad_speech_start(self, event) -> None:
        """处理VAD语音开始事件"""
        logger.info(
            "VAD语音开始，暂停TTS并发布tts 暂停事件"
        )
        await self._publish_tts_pause(self.current_task_id, self.current_text)
        await self._pause_tts()

    def _generate_task_id(self) -> int:
        """生成任务ID"""
        self.current_task_id += 1
        return self.current_task_id

    async def shutdown(self) -> None:
        """关闭TTS管理器"""
        # 停用TTS
        await self.reset_tts()

        logger.info("TTS管理器已关闭（shutdown）")

    async def generate_tts_from_text(self, text: str) -> None:
        """从文本生成TTS音频并放入队列"""
        task_id = self.current_task_id
        logger.info(
            "开始TTS生成，输入文本: %s, 任务ID: %s",
            text,
            task_id,
        )

        try:
            loop = asyncio.get_running_loop()

            # 直接使用同步生成器，避免async for的问题
            def _gen():
                try:
                    for output in self.pipeline.generate_stream(text=text):
                        yield output
                except Exception as e:
                    logger.error("TTS生成器内部异常: %s", e)
                    raise

            # 改为异步迭代，每个音频块生成后立即处理
            resp_text = ""
            chunk_count = 0
            sync_gen = _gen()

            try:
                while True:
                    try:
                        # 在线程池中执行同步生成器的next操作，使用更安全的方式
                        def safe_next():
                            try:
                                return next(sync_gen)
                            except StopIteration:
                                return None  # 返回None表示生成器结束

                        o = await loop.run_in_executor(None, safe_next)

                        # 如果返回None，说明生成器已经结束
                        if o is None:
                            logger.debug(
                                "TTS同步生成器正常结束，任务ID: %s",
                                task_id,
                            )
                            break

                        ch = o.audio
                        new_text = o.text

                        if not resp_text.endswith(new_text):
                            resp_text += new_text

                        # 将音频块和文本更新放入队列
                        await self.tts_queue.put(
                            TTSQueueItem(task_id, ch, resp_text, False)
                        )
                        chunk_count += 1
                        logger.debug(
                            "TTS生成第%d个音频块，任务ID: %s",
                            chunk_count,
                            task_id,
                        )

                    except Exception as e:
                        logger.error(
                            "TTS生成过程中发生异常: %s, 任务ID: %s",
                            e,
                            task_id,
                        )
                        break

                # 生成器完成后的处理
                logger.debug(
                    "TTS生成器完成，任务ID: %s, 累积文本: %s, 音频块数: %d",
                    task_id,
                    resp_text,
                    chunk_count,
                )

                if resp_text:
                    await self.tts_queue.put(
                        TTSQueueItem(task_id, b"", resp_text, True)
                    )
                    logger.info(
                        "TTS生成完成，任务ID: %s, 最终文本: %s, 音频块数: %d",
                        task_id,
                        resp_text,
                        chunk_count
                    )
                else:
                    logger.warning(
                        "TTS生成完成但无文本输出，任务ID: %s",
                        task_id
                    )

            except Exception as e:
                logger.error(
                    "TTS生成循环中发生异常: %s, 任务ID: %s",
                    e,
                    task_id
                )
                # 即使发生异常，也要尝试发送最终结果
                if resp_text:
                    await self.tts_queue.put(
                        TTSQueueItem(task_id, b"", resp_text, True)
                    )
                    logger.info(
                        "TTS异常后仍发送最终结果，任务ID: %s, 文本: %s",
                        task_id,
                        resp_text
                    )
            finally:
                # 确保同步生成器被正确关闭
                if hasattr(sync_gen, "close"):
                    try:
                        sync_gen.close()
                    except Exception:
                        pass

        except asyncio.CancelledError:
            logger.info(
                "TTS生产者被取消，任务ID: %s", task_id
            )
        except Exception as e:
            logger.error(
                "TTS生成异常，任务ID: %s, 错误: %s",
                task_id,
                e
            )
            # 发布错误事件
            error_event = EventFactory.create_error(
                error_type="tts_generation_error",
                error_message=str(e),
                component="TTSManager",
            )
            await self.event_bus.publish(error_event)
