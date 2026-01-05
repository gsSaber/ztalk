# -*- coding: utf-8 -*-
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import ClassVar, Dict, Any, Optional


@dataclass
class BaseEvent:
    event_id: str
    timestamp: float
    TYPE: ClassVar[str] = "base"

    @property
    def event_type(self) -> str:
        return self.TYPE

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["event_type"] = self.TYPE
        return d


@dataclass
class WebSocketMessageReceived(BaseEvent):
    TYPE: ClassVar[str] = "websocket.message_received"
    message: str = ""


@dataclass
class AudioFrameReceived(BaseEvent):
    TYPE: ClassVar[str] = "audio.frame_received"
    audio_data: bytes = b""
    sample_rate: int = 48000
    channels: int = 1
    is_final: bool = False
    audio_format: str = "pcm_s16le"


@dataclass
class VADSpeechStart(BaseEvent):
    TYPE: ClassVar[str] = "vad.speech_start"
    confidence: float = 0.0
    speech_probability: float = 0.0


@dataclass
class VADSpeechEnd(BaseEvent):
    TYPE: ClassVar[str] = "vad.speech_end"
    confidence: float = 0.0
    speech_probability: float = 0.0


@dataclass
class ASRResultPartial(BaseEvent):
    TYPE: ClassVar[str] = "asr.result_partial"
    text: str = ""
    confidence: float = 0.0
    is_final: bool = False


@dataclass
class ASRResultFinal(BaseEvent):
    TYPE: ClassVar[str] = "asr.result_final"
    text: str = ""
    confidence: float = 0.0
    is_final: bool = True


@dataclass
class ConversationStateChanged(BaseEvent):
    TYPE: ClassVar[str] = "conversation.state_changed"
    from_state: str = ""
    to_state: str = ""
    reason: str = ""


@dataclass
class TTSStarted(BaseEvent):
    TYPE: ClassVar[str] = "tts.started"
    text: str = ""
    task_id: int = 0


@dataclass
class TTSStopped(BaseEvent):
    TYPE: ClassVar[str] = "tts.stopped"
    text: str = ""
    task_id: int = 0


@dataclass
class TTSPaused(BaseEvent):
    TYPE: ClassVar[str] = "tts.paused"
    text: str = ""
    task_id: int = 0


@dataclass
class TTSResponseUpdate(BaseEvent):
    TYPE: ClassVar[str] = "tts.response_update"
    text: str = ""
    task_id: int = 0


@dataclass
class TTSResponseFinish(BaseEvent):
    TYPE: ClassVar[str] = "tts.response_finish"
    text: str = ""
    task_id: int = 0


@dataclass
class TTSChunkGenerated(BaseEvent):
    TYPE: ClassVar[str] = "tts.chunk_generated"
    audio_chunk: bytes = b""
    task_id: int = 0
    text: str = ""


@dataclass
class TTSPlaybackFinished(BaseEvent):
    TYPE: ClassVar[str] = "tts.playback_finished"
    final_text: str = ""


@dataclass
class VerificationResult(BaseEvent):
    TYPE: ClassVar[str] = "verification.result"
    is_valid: bool = False
    text: str = ""
    confidence: float = 0.0
    reason: str = ""
    validation_time: float = 0.0
    text_length: int = 0
    chunk_count: int = 0


@dataclass
class ErrorOccurred(BaseEvent):
    TYPE: ClassVar[str] = "error.occurred"
    error_type: str = ""
    error_message: str = ""
    component: str = ""
    context: Dict[str, Any] = field(default_factory=dict)


class EventFactory:
    @staticmethod
    def create_websocket_message_received(
         message: str
    ) -> WebSocketMessageReceived:
        return WebSocketMessageReceived(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            message=message,
        )

    @staticmethod
    def create_audio_frame_received(
        audio_data: bytes,
        sample_rate: int = 48000,
        is_final: bool = False,
    ) -> AudioFrameReceived:
        return AudioFrameReceived(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            audio_data=audio_data,
            sample_rate=sample_rate,
            is_final=is_final,
            audio_format="pcm_s16le",
        )

    @staticmethod
    def create_vad_speech_start(
        confidence: float = 0.0
    ) -> VADSpeechStart:
        return VADSpeechStart(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            confidence=confidence,
            speech_probability=confidence,
        )

    @staticmethod
    def create_vad_speech_end(confidence: float = 0.0) -> VADSpeechEnd:
        return VADSpeechEnd(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            confidence=confidence,
            speech_probability=confidence,
        )

    @staticmethod
    def create_asr_result(
        text: str, is_final: bool = False, confidence: float = 0.0
    ) -> BaseEvent:
        if is_final:
            return ASRResultFinal(
                event_id=str(uuid.uuid4()),
                timestamp=time.time(),
                text=text,
                confidence=confidence,
            )
        else:
            return ASRResultPartial(
                event_id=str(uuid.uuid4()),
                timestamp=time.time(),
                text=text,
                confidence=confidence,
            )

    @staticmethod
    def create_tts_started(text: str, task_id: int) -> TTSStarted:
        return TTSStarted(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            text=text,
            task_id=task_id,
        )

    @staticmethod
    def create_tts_stopped(text: str, task_id: int) -> TTSStopped:
        return TTSStopped(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            text=text,
            task_id=task_id,
        )

    @staticmethod
    def create_tts_paused(text: str, task_id: int) -> TTSPaused:
        return TTSPaused(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            text=text,
            task_id=task_id,
        )

    @staticmethod
    def create_tts_response_update(
        task_id: int, text: str
    ) -> TTSResponseUpdate:
        return TTSResponseUpdate(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            text=text,
            task_id=task_id,
        )

    @staticmethod
    def create_tts_response_finish(
        text: str, task_id: int
    ) -> TTSResponseFinish:
        return TTSResponseFinish(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            text=text,
            task_id=task_id,
        )

    @staticmethod
    def create_tts_chunk_generated(
        audio_chunk: bytes, task_id: int, text: str = ""
    ) -> TTSChunkGenerated:
        return TTSChunkGenerated(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            audio_chunk=audio_chunk,
            task_id=task_id,
            text=text,
        )

    @staticmethod
    def create_tts_playback_finished(
        final_text: str
    ) -> TTSPlaybackFinished:
        return TTSPlaybackFinished(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            final_text=final_text,
        )

    @staticmethod
    def create_error(
        error_type: str,
        error_message: str,
        component: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ErrorOccurred:
        return ErrorOccurred(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            error_type=error_type,
            error_message=error_message,
            component=component,
            context=context or {},
        )

    @staticmethod
    def create_verification_result(
        session_id: str,
        is_valid: bool,
        text: str,
        confidence: float,
        reason: str,
        text_length: int = 0,
        chunk_count: int = 0,
    ) -> VerificationResult:
        return VerificationResult(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            is_valid=is_valid,
            text=text,
            confidence=confidence,
            reason=reason,
            validation_time=time.time(),
            text_length=text_length,
            chunk_count=chunk_count,
        )
