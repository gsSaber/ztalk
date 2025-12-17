# -*- coding: utf-8 -*-
import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Callable, Any, Optional, Set, Type, Union
import weakref

from logger import *

from .events import BaseEvent, EventFactory


@dataclass
class EventHandler:
    """事件处理器包装类"""
    handler: Callable


class EventBus:
    """事件总线"""

    def __init__(self, max_history: int = 1000):
        """
        初始化事件总线

        Args:
            enable_history: 是否启用事件历史记录
            max_history: 最大历史记录数量
        """
        # 事件处理器映射，统一按事件类型字符串作为键
        # {event_type(str): [EventHandler]}
        self._handlers: Dict[str, List[EventHandler]] = defaultdict(list)

        # 事件历史记录
        self._max_history = max_history

        # 统计信息
        self._stats = {
            "events_published": 0,
            "events_processed": 0,
            "errors_occurred": 0,
            "handlers_count": 0,
        }

        # 活跃的异步任务
        self._active_tasks: Set[asyncio.Task] = set()

    def _get_event_key(self, event_identifier: Union[Type[BaseEvent], str]) -> str:
        """将事件标识（事件类或事件类型字符串）标准化为事件类型字符串键"""
        # 已是字符串类型
        if isinstance(event_identifier, str):
            return event_identifier
        # 事件类，优先使用 TYPE
        try:
            evt_type = getattr(event_identifier, "TYPE", None)
            if isinstance(evt_type, str) and evt_type:
                return evt_type
        except Exception:
            pass
        # 退化为类名字符串
        try:
            return event_identifier.__name__
        except Exception:
            return str(event_identifier)

    def subscribe(
        self,
        event_class: Union[Type[BaseEvent], str],
        handler: Callable[[BaseEvent], Any],
    ) -> None:
        """
        订阅事件

        Args:
            event_class: 事件类（BaseEvent 子类）或事件类型字符串（如 "tts.started"）
            handler: 事件处理函数
            priority: 优先级，数字越大优先级越高
            session_filter: 会话过滤器，只处理特定会话的事件
        """
        event_handler = EventHandler(
            handler=handler
        )
        key = self._get_event_key(event_class)
        self._handlers[key].append(event_handler)

    async def publish(
        self, event: BaseEvent, wait_for_completion: bool = False
    ) -> bool:
        """
        发布事件

        Args:
            event: 要发布的事件
            wait_for_completion: 是否等待所有处理器完成

        Returns:
            是否成功发布
        """
        try:
            self._stats["events_published"] += 1

            # 获取事件处理器（按事件类型字符串匹配）
            event_type = event.event_type
            handlers = self._handlers.get(event_type, [])
            if not handlers:
                logger.debug("没有找到事件处理器: %s", event_type)
                return True

            # 创建处理任务
            tasks = []
            for handler in handlers:
                task = asyncio.create_task(self._handle_event_safe(handler, event))
                tasks.append(task)
                self._active_tasks.add(task)

                # 任务完成后清理
                task.add_done_callback(self._active_tasks.discard)

            if wait_for_completion and tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            return True

        except Exception as e:
            logger.error("发布事件失败: %s", e)

            # 发布错误事件
            if event.event_type != "error.occurred":
                error_event = EventFactory.create_error(
                    error_type="event_bus_publish_error",
                    error_message=str(e),
                    component="EventBus",
                )
                # 异步发布错误事件，避免递归
                asyncio.create_task(self.publish(error_event))

            return False

    async def _handle_event_safe(self, handler: EventHandler, event: BaseEvent) -> None:
        """
        安全处理事件，捕获异常

        Args:
            handler: 事件处理器
            event: 事件对象
        """
        try:
            # 调用处理器
            if asyncio.iscoroutinefunction(handler.handler):
                await handler.handler(event)
            else:
                handler.handler(event)

        except Exception as e:
            logger.error("事件处理器异常: %s, event_type: %s", e, event.event_type)
            # 发布错误事件
            if event.event_type != "error.occurred":
                error_event = EventFactory.create_error(
                    error_type="event_handler_error",
                    error_message=str(e),
                    component=f"Handler:{handler.handler.__name__}",
                )
                # 创建异步任务发布错误事件
                error_task = asyncio.create_task(self.publish(error_event))
                self._active_tasks.add(error_task)
                error_task.add_done_callback(self._active_tasks.discard)


    async def _wait_for_all_handlers(self, timeout: float = 3.0):
        """
        等待所有活跃的处理器完成

        Args:
            timeout: 超时时间（秒）

        Returns:
            是否所有处理器都完成
        """
        if not self._active_tasks:
            return

        try:
            await asyncio.wait_for(
                asyncio.gather(*self._active_tasks, return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "等待事件处理器超时，仍有 %d 个任务未完成，强制取消",
                len(self._active_tasks),
            )
            for task in self._active_tasks:
                if not task.done():
                    task.cancel()

    async def shutdown(self) -> None:
        """
        关闭事件总线，清理资源
        """
        logger.info("正在关闭事件总线...")

        # 等待所有活跃任务完成
        await self._wait_for_all_handlers(timeout=3.0)

        # 清理资源
        self._handlers.clear()
        self._active_tasks.clear()

        logger.info("事件总线已关闭")

    def __del__(self):
        """析构函数"""
        # 清理资源
        if hasattr(self, "_active_tasks"):
            for task in self._active_tasks:
                if not task.done():
                    task.cancel()
