from funasr import AutoModel
from typing import Optional, Dict, Any
import tempfile
import os
import numpy as np
import torchaudio
import torch


class ParaformerLocal:
    TARGET_SAMPLE_RATE = 16000

    def __init__(
        self,
        model: str = "paraformer-zh-streaming",
        vad_model: Optional[str] = "fsmn-vad",
        punc_model: Optional[str] = "ct-punc",
        spk_model: Optional[str] = None,
        device: str = "cpu",
        ncpu: int = 4,
        output_dir: Optional[str] = None,
        batch_size: int = 1,
        hub: str = "ms",
        batch_size_s: int = 300,
        hotword: Optional[str] = None,
        disable_update: bool = True,
        chunk_size: Optional[list] = [0, 10, 5],  # [0, 10, 5] 600ms
        encoder_chunk_look_back: int = 4,  # number of chunks to lookback for encoder self-attention
        decoder_chunk_look_back: int = 1,  # number of encoder chunks to lookback for decoder cross-attention
        **kwargs: Dict[str, Any],
    ):
        """
        本地paraformer ASR实现

        Args:
            model (str): 模型名称或本地路径，默认为"paraformer-zh-streaming"
            vad_model (str, optional): VAD模型名称，默认为"fsmn-vad"；流式识别时为None
            punc_model (str, optional): 标点符号模型名称，默认为"ct-punc"；流式识别时为None
            spk_model (str, optional): 说话人分离模型名称，默认为None；流式识别时为None
            device (str): 设备选择，cuda:0(默认GPU0)/cpu/mps(Mac M系列)/xpu(Intel GPU)
            ncpu (int): CPU线程数，默认为4
            output_dir (str, optional): 结果输出路径，默认为None
            batch_size (int): 解码批大小，默认为1
            hub (str): 模型下载源，ms(ModelScope)/hf(Hugging Face)
            batch_size_s (int): 生成时批处理大小（秒），默认为300
            hotword (str, optional): 热词，默认为None
            disable_update (bool): 是否禁用模型更新检查，默认为True
            chunk_size (list, optional): 流式识别的chunk大小设置，默认[0, 10, 5] 600ms
            encoder_chunk_look_back (int): encoder自注意力回看的chunk数，默认4
            decoder_chunk_look_back (int): decoder交叉注意力回看的chunk数，默认1
            **kwargs: config.yaml中的任何参数，如max_single_segment_time=6000
        """
        self.model_name = model
        self.vad_model = vad_model
        self.punc_model = punc_model
        self.spk_model = spk_model
        self.device = device
        self.ncpu = ncpu
        self.output_dir = output_dir
        self.batch_size = batch_size
        self.hub = hub
        self.batch_size_s = batch_size_s
        self.hotword = hotword
        self.disable_update = disable_update
        self.kwargs = kwargs

        # 流式识别相关参数
        self.chunk_size = chunk_size
        self.encoder_chunk_look_back = encoder_chunk_look_back
        self.decoder_chunk_look_back = decoder_chunk_look_back
        self.chunk_secs = self.chunk_size[1] * 0.06

        # 初始化模型
        self._init_model()

    def _init_model(self):
        """初始化funasr模型"""
        try:
            # 构建模型参数
            model_kwargs = {
                "model": self.model_name,
                "device": self.device,
                "ncpu": self.ncpu,
                "batch_size": self.batch_size,
                "hub": self.hub,
                "disable_update": self.disable_update,
            }

            # 添加可选模型
            if self.vad_model and not self.model_name.endswith("streaming"):
                model_kwargs["vad_model"] = self.vad_model
            if self.punc_model and not self.model_name.endswith("streaming"):
                model_kwargs["punc_model"] = self.punc_model
            if self.spk_model and not self.model_name.endswith("streaming"):
                model_kwargs["spk_model"] = self.spk_model

            # 添加输出目录
            if self.output_dir:
                model_kwargs["output_dir"] = self.output_dir

            # 添加额外配置参数
            if self.kwargs:
                model_kwargs.update(self.kwargs)

            self.model = AutoModel(**model_kwargs)
        except Exception as e:
            raise RuntimeError(f"初始化paraformer模型失败: {e}")

    def _generate_text(self, audio_path: str) -> str:
        """
        使用模型生成文本

        Args:
            audio_path (str): 音频文件路径

        Returns:
            str: 识别的文本
        """
        # 构建生成参数
        generate_kwargs = {
            "input": audio_path,
            "batch_size_s": self.batch_size_s,
        }

        if self.hotword:
            generate_kwargs["hotword"] = self.hotword

        # 调用模型进行识别
        result = self.model.generate(**generate_kwargs)

        # 解析结果
        if isinstance(result, list) and len(result) > 0:
            # 如果结果是列表，提取文本内容
            if isinstance(result[0], dict) and "text" in result[0]:
                return "".join([item.get("text", "") for item in result])
            elif isinstance(result[0], str):
                return "".join(result)
            else:
                return str(result[0])
        elif isinstance(result, dict) and "text" in result:
            return result["text"]
        else:
            return str(result)

    def set_hotword(self, hotword: str):
        """设置热词"""
        self.hotword = hotword

    def set_device(self, device: str):
        """设置设备"""
        self.device = device
        # 需要重新初始化模型
        self._init_model()

    def get_model_info(self) -> dict:
        """获取模型信息"""
        return {
            "model": self.model_name,
            "vad_model": self.vad_model,
            "punc_model": self.punc_model,
            "spk_model": self.spk_model,
            "device": self.device,
            "ncpu": self.ncpu,
            "output_dir": self.output_dir,
            "batch_size": self.batch_size,
            "hub": self.hub,
            "batch_size_s": self.batch_size_s,
            "hotword": self.hotword,
            "extra_kwargs": self.kwargs,
        }

    def recognize(self, audio: np.ndarray) -> str:
        """
        将音频转换为文本
        Args:
            audio (np.ndarray): 音频数据，float32类型numpy数组
        Returns:
            str: 识别的文本
        """
        try:
            if isinstance(audio, bytes):
                # 如果是字节数据，保存为临时文件
                with tempfile.NamedTemporaryFile(
                    suffix=".wav", delete=False
                ) as temp_file:
                    temp_file.write(audio)
                    temp_audio_path = temp_file.name

                try:
                    result = self._generate_text(temp_audio_path)
                finally:
                    # 清理临时文件
                    if os.path.exists(temp_audio_path):
                        os.unlink(temp_audio_path)

                return result
            else:
                # 如果是文件路径
                return self._generate_text(audio)

        except Exception as e:
            raise RuntimeError(f"语音识别失败: {e}")

    def recognize_stream(self, audio: np.ndarray, cache: dict, is_final: bool) -> str:
        """
        流式识别音频

        Args:
            audio (np.ndarray): 音频数据，float32类型numpy数组
            cache (dict): 缓存字典，用于存储流式识别的中间状态
            is_final (bool): 是否为最后一个音频片段

        Returns:
            str: 识别的文本
        """
        # 如果模型名称不以streaming结尾，直接调用recognize
        if not self.model_name.endswith("streaming"):
            return self.recognize(audio)

        try:
            # 如果输入是bytes或str类型，需要先转换为numpy数组
            if isinstance(audio, (bytes, str)):
                import soundfile as sf

                if isinstance(audio, bytes):
                    with tempfile.NamedTemporaryFile(
                        suffix=".wav", delete=False
                    ) as temp_file:
                        temp_file.write(audio)
                        temp_audio_path = temp_file.name
                else:
                    temp_audio_path = audio

                try:
                    speech, _ = sf.read(temp_audio_path)
                finally:
                    # 如果是临时文件，清理它
                    if isinstance(audio, bytes) and os.path.exists(temp_audio_path):
                        os.unlink(temp_audio_path)
            else:
                speech = audio

            # 调用模型进行流式识别
            result = self.model.generate(
                input=speech,
                cache=cache,
                is_final=is_final,
                chunk_size=self.chunk_size,
                encoder_chunk_look_back=self.encoder_chunk_look_back,
                decoder_chunk_look_back=self.decoder_chunk_look_back,
            )
            # 解析结果
            if isinstance(result, list) and len(result) > 0:
                if isinstance(result[0], dict) and "text" in result[0]:
                    return "".join([item.get("text", "") for item in result])
                elif isinstance(result[0], str):
                    return "".join(result)
                else:
                    return str(result[0])
            elif isinstance(result, dict) and "text" in result:
                return result["text"]
            else:
                return str(result)

        except Exception as e:
            raise RuntimeError(f"流式语音识别失败: {e}")

    def is_streaming(self) -> bool:
        """
        Check if the ASR is in streaming mode.
        """
        return self.model_name.endswith("streaming")

    def resample(self, audio: np.ndarray, ori_sampling_rate: int) -> np.ndarray:
        """
        Resample audio to the model's sampling rate.
        """
        if ori_sampling_rate != self.TARGET_SAMPLE_RATE:
            # Use torchaudio.transforms.Resample to resample audio
            audio = torch.FloatTensor(audio)
            resampler = torchaudio.transforms.Resample(
                orig_freq=ori_sampling_rate, new_freq=self.TARGET_SAMPLE_RATE
            )
            audio = resampler(audio)
            audio = audio.numpy()
        return audio

    def get_chunks(self, audio: np.ndarray, ori_sampling_rate: int) -> list[np.ndarray]:
        audio = self.resample(audio, ori_sampling_rate)
        chunk_stride = int(self.chunk_secs * self.TARGET_SAMPLE_RATE)
        total_chunk_num = int(len(audio - 1) / chunk_stride + 1)
        chunks = []
        for i in range(total_chunk_num):
            chunks.append(audio[i * chunk_stride : (i + 1) * chunk_stride])
        return chunks
