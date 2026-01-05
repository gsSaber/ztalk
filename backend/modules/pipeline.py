from typing import TypedDict, Union, Optional, Iterable, Tuple, List
import time
from logger import logger

class PipelineOutput:
    """
    TypedDict for the output of the pipeline.

    audio: PCM 16bit mono, 48000Hz bytes
    """
    def __init__(self,audio,text,asr_text):
        self.audio = audio
        self.text = text
        self.asr_text = asr_text

# class SimplePipeline:
#     def __init__(
#         self,
#         asr_model,
#         llm_agent,
#         tts_model,
#         default_response: str = "对不起，我没听清，请您再说一遍",
#         use_streaming_tts: bool = True,
#     ):
#         self.asr_model = asr_model
#         self.llm_agent = llm_agent
#         self.tts_model = tts_model
#         self.default_response = default_response
#         self.use_streaming_tts = use_streaming_tts

#     def _validate_inputs(
#         self, audio: Optional[Union[str, bytes]] = None, text: Optional[str] = None
#     ) -> None:
#         """验证输入参数的有效性"""
#         if text is not None and audio is not None:
#             raise ValueError("audio and text cannot be present at the same time")
#         if text is None and audio is None:
#             raise ValueError("either audio or text must be provided")

#     def _process_audio_input(self, audio: Union[str, bytes]) -> str:
#         """处理音频输入，返回识别的文本"""
#         recognized_text = self.asr_model.recognize(audio)
#         return recognized_text

#     def _get_input_text(
#         self, audio: Optional[Union[str, bytes]] = None, text: Optional[str] = None
#     ) -> Tuple[str, Optional[str]]:
#         """获取输入文本和ASR识别文本（如果有）"""
#         self._validate_inputs(audio, text)

#         if text is not None:
#             return text, None
#         else:
#             start_time = time.time()
#             recognized_text = self._process_audio_input(audio)
#             logger.debug(
#                 f"Non-streaming ASR inference time: {time.time() - start_time:.4f}s"
#             )
#             return recognized_text, recognized_text

#     def _synthesize_with_fallback(self, text: str, context: str = "") -> bytes:
#         """TTS合成，失败时使用默认响应（非流式版本）"""
#         try:
#             audio_output = self.tts_model.synthesize(text)
#             return audio_output
#         except Exception as e:
#             # 回退到默认响应
#             try:
#                 return self.tts_model.synthesize(self.default_response)
#             except Exception as fallback_error:
#                 raise fallback_error

#     def _synthesize_stream_with_fallback(
#         self, text: str, context: str = ""
#     ) -> Iterable[bytes]:
#         """TTS流式合成，失败时使用默认响应"""
#         try:
#             # 使用流式TTS合成
#             for audio_chunk in self.tts_model.synthesize_stream(text):
#                 yield audio_chunk
#         except Exception as e:
#             logger.error(f"Failed to synthesize TTS: {e}")
#             # 回退到默认响应的流式合成
#             try:
#                 for audio_chunk in self.tts_model.synthesize_stream(
#                     self.default_response
#                 ):
#                     yield audio_chunk
#             except Exception:
#                 # 最后的回退：使用非流式方法
#                 fallback_audio = self.tts_model.synthesize(self.default_response)
#                 yield fallback_audio

#     def _split_text_by_delimiters(self, accumulated_text: str) -> Tuple[List[str], str]:
#         """根据分隔符分割文本，返回完整句子列表和剩余文本"""
#         sentences = []
#         temp_text = accumulated_text

#         # 找到所有的逗号和句号位置，增加冒号作为分隔符
#         for delimiter in ["。", "，", "！", "!", ".", ",", "："]:
#             if delimiter in temp_text:
#                 parts = temp_text.split(delimiter)
#                 if len(parts) > 1:
#                     # 保留除了最后一个部分的所有内容（因为最后一个部分可能不完整）
#                     for i in range(len(parts) - 1):
#                         if parts[i].strip():
#                             sentences.append(parts[i].strip() + delimiter)
#                     # 更新累积文本为最后一个未完成的部分
#                     temp_text = parts[-1]
#                     break

#         return sentences, temp_text

#     def _create_pipeline_output(
#         self, audio: bytes, text: str, asr_text: Optional[str] = None
#     ) -> PipelineOutput:
#         """创建PipelineOutput对象"""
#         return PipelineOutput(
#             audio=audio,
#             text=text,
#             asr_text=asr_text,
#         )

#     def _yield_tts_output(
#         self, text: str, asr_text: Optional[str], context: str = ""
#     ) -> Iterable[PipelineOutput]:
#         """TTS合成并yield输出，包含错误处理"""
#         try:
#             audio_output = self._synthesize_with_fallback(text, context)
#             yield self._create_pipeline_output(audio_output, text, asr_text)
#         except Exception as e:
#             # 如果连默认响应都失败了，yield默认响应但不包含音频
#             yield self._create_pipeline_output(b"", self.default_response, asr_text)

#     def _yield_tts_stream_output(
#         self, text: str, asr_text: Optional[str], context: str = ""
#     ) -> Iterable[PipelineOutput]:
#         """TTS流式合成并yield输出，包含错误处理"""
#         try:
#             for audio_chunk in self._synthesize_stream_with_fallback(text, context):
#                 # 每个音频块都作为单独的输出yield
#                 yield self._create_pipeline_output(audio_chunk, text, asr_text)

#         except Exception as e:
#             # 如果流式合成完全失败，yield默认响应但不包含音频
#             yield self._create_pipeline_output(b"", self.default_response, asr_text)

#     def generate(
#         self,
#         audio: Optional[Union[str, bytes]] = None,
#         text: Optional[str] = None,
#         generation_args: Optional[dict] = None,
#     ) -> PipelineOutput:
#         if generation_args is None:
#             generation_args = {}

#         # 获取输入文本
#         input_text, recognized_text = self._get_input_text(audio, text)
#         logger.debug(f"Input text: {input_text}")
#         # 生成响应文本
#         start_time = time.time()
#         response_text = self.llm_agent.generate(input_text, **generation_args)
#         logger.debug(f"Task agent inference time: {time.time() - start_time:.4f}s")

#         # TTS合成
#         start_time = time.time()
#         audio_output = self._synthesize_with_fallback(response_text)
#         logger.debug(f"TTS inference time: {time.time() - start_time:.4f}s")

#         return self._create_pipeline_output(
#             audio_output, response_text, recognized_text
#         )

#     # Another version of generate_stream, split text by delimiters first before TTS
#     def generate_stream(
#         self,
#         audio: Optional[Union[str, bytes]] = None,
#         text: Optional[str] = None,
#         generation_args: Optional[dict] = None,
#     ) -> Iterable[PipelineOutput]:
#         if generation_args is None:
#             generation_args = {}

#         # 获取输入文本
#         input_text, recognized_text = self._get_input_text(audio, text)

#         # 收集生成的文本片段
#         accumulated_text = ""

#         # TODO: improve first chunk splitting logic
#         no_sentence_processed = True
#         FIRST_CHUNK_LEN = 5

#         # 从task_driven_agent流式生成
#         for response_chunk in self.llm_agent.generate_stream(
#             input_text, **generation_args
#         ):
#             accumulated_text += response_chunk

#             # 分割文本
#             sentences, remaining_text = self._split_text_by_delimiters(accumulated_text)

#             # 处理完整的句子 - 根据配置选择TTS方式
#             for sentence in sentences:
#                 if self.use_streaming_tts:
#                     yield from self._yield_tts_stream_output(
#                         sentence, recognized_text, f"'{sentence}'"
#                     )
#                 else:
#                     yield from self._yield_tts_output(
#                         sentence, recognized_text, f"'{sentence}'"
#                     )

#             # 更新累积文本
#             accumulated_text = remaining_text

#         # 处理最后剩余的文本（如果有的话） - 根据配置选择TTS方式
#         if accumulated_text.strip():
#             if self.use_streaming_tts:
#                 yield from self._yield_tts_stream_output(
#                     accumulated_text.strip(),
#                     recognized_text,
#                     f"final text '{accumulated_text.strip()}'",
#                 )
#             else:
#                 yield from self._yield_tts_output(
#                     accumulated_text.strip(),
#                     recognized_text,
#                     f"final text '{accumulated_text.strip()}'",
#                 )

#     def copy(self) -> "SimplePipeline":
#         return SimplePipeline(
#             self.asr_model,
#             self.llm_agent.copy(),
#             self.tts_model,
#             self.default_response,
#             self.use_streaming_tts,
#         )

#     def get_asr_model(self):
#         return self.asr_model

#     def get_tts_model(self):
#         return self.tts_model



class SimplePipeline:
    def __init__(
        self,
        asr_model,
        llm,
        tts_model,
        default_response: str = "对不起，我没听清，请您再说一遍",
        use_streaming_tts: bool = True,
    ):
        self.asr_model = asr_model
        self.llm = llm
        self.tts_model = tts_model
        self.default_response = default_response
        self.use_streaming_tts = use_streaming_tts

    def _process_audio_input(self, audio: Union[str, bytes]) -> str:
        """处理音频输入，返回识别的文本"""
        recognized_text = self.asr_model.recognize(audio)
        return recognized_text

    def _extract_text(self, chunk) -> str:
        """从LLM流式chunk中提取文本，兼容字符串和AIMessageChunk"""
        if isinstance(chunk, str):
            return chunk

        text = getattr(chunk, "content", None)
        if text:
            return text

        message = getattr(chunk, "message", None)
        if message:
            content = getattr(message, "content", None)
            if content:
                return content

        text_attr = getattr(chunk, "text", None)
        if text_attr:
            return text_attr

        return ""
    
    def _synthesize_stream_with_fallback(
        self, text: str
    ) -> Iterable[bytes]:
        """TTS流式合成，失败时使用默认响应"""
        try:
            # 使用流式TTS合成
            for audio_chunk in self.tts_model.synthesize_stream(text):
                yield audio_chunk
        except Exception as e:
            logger.error(f"Failed to synthesize TTS: {e}")

    def _create_pipeline_output(
        self, audio: bytes, text: str, asr_text: Optional[str] = None
    ) -> PipelineOutput:
        """创建PipelineOutput对象"""
        return PipelineOutput(
            audio=audio,
            text=text,
            asr_text=asr_text,
        )

    def _split_text_by_delimiters(self, accumulated_text: str) -> Tuple[List[str], str]:
        """根据分隔符分割文本，返回完整句子列表和剩余文本"""
        sentences = []
        temp_text = accumulated_text

        # 找到所有的逗号和句号位置，增加冒号作为分隔符
        for delimiter in ["。", "，", "！", "!", ".", ",", "："]:
            if delimiter in temp_text:
                parts = temp_text.split(delimiter)
                if len(parts) > 1:
                    # 保留除了最后一个部分的所有内容（因为最后一个部分可能不完整）
                    for i in range(len(parts) - 1):
                        if parts[i].strip():
                            sentences.append(parts[i].strip() + delimiter)
                    # 更新累积文本为最后一个未完成的部分
                    temp_text = parts[-1]
                    break

        return sentences, temp_text
    
    def _yield_tts_stream_output(
        self, text: str, asr_text: Optional[str]
    ) -> Iterable[PipelineOutput]:
        """TTS流式合成并yield输出，包含错误处理"""
        try:
            for audio_chunk in self._synthesize_stream_with_fallback(text):
                # 每个音频块都作为单独的输出yield
                yield self._create_pipeline_output(audio_chunk, text, asr_text)

        except Exception as e:
            # 如果流式合成完全失败，yield默认响应但不包含音频
            yield self._create_pipeline_output(b"", self.default_response, asr_text)

    # Another version of generate_stream, split text by delimiters first before TTS
    def generate_stream(
        self,
        text: Optional[str] = None,
        generation_args: Optional[dict] = None,
    ) -> Iterable[PipelineOutput]:
        if generation_args is None:
            generation_args = {}

        # 收集生成的文本片段
        accumulated_text = ""
        
        # 从task_driven_agent流式生成
        for response_chunk in self.llm.generate_stream(input=text):
            chunk_text = self._extract_text(response_chunk)
            if not chunk_text:
                continue

            accumulated_text += chunk_text

            # 分割文本
            sentences, remaining_text = self._split_text_by_delimiters(accumulated_text)

            # 处理完整的句子 - 根据配置选择TTS方式
            for sentence in sentences:
                yield from self._yield_tts_stream_output(
                    sentence, text
                )

            # 更新累积文本
            accumulated_text = remaining_text

        # 处理最后剩余的文本（如果有的话） - 根据配置选择TTS方式
        if accumulated_text.strip():
            yield from self._yield_tts_stream_output(
                accumulated_text.strip(),
                text
            )

    def get_asr_model(self):
        return self.asr_model
