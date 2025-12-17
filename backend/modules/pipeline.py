from typing import Union, Optional, Iterable, Tuple, List
import time
from logger import logger



class SimplePipeline:
    def __init__(
        self,
        asr_model,
        default_response: str = "对不起，我没听清，请您再说一遍",
        use_streaming_tts: bool = True,
    ):
        self.asr_model = asr_model
        self.default_response = default_response
        self.use_streaming_tts = use_streaming_tts

    def _process_audio_input(self, audio: Union[str, bytes]) -> str:
        """处理音频输入，返回识别的文本"""
        recognized_text = self.asr_model.recognize(audio)
        return recognized_text


    def get_asr_model(self):
        return self.asr_model
