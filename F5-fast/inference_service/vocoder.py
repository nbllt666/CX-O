import torch
import tensorrt as trt
import numpy as np
from pathlib import Path
from typing import Optional


class Vocoder:
    def __init__(
        self,
        engine_path: str,
        device: torch.device = torch.device("cuda:0"),
        stream: Optional[torch.cuda.Stream] = None,
    ):
        self.device = device
        self.engine_path = Path(engine_path)
        self.stream = stream if stream else torch.cuda.Stream(device)
        
        self.trt_logger = trt.Logger(trt.Logger.WARNING)
        self.runtime = trt.Runtime(self.trt_logger)
        
        self._load_engine()
        
    def _load_engine(self):
        if not self.engine_path.exists():
            raise FileNotFoundError(f"Vocoder engine not found: {self.engine_path}")
        
        with open(self.engine_path, "rb") as f:
            self.engine_buffer = f.read()
        
        self.engine = self.runtime.deserialize_cuda_engine(self.engine_buffer)
        self.context = self.engine.create_execution_context()
        
    def decode(self, mel: torch.Tensor) -> torch.Tensor:
        mel = mel.to(torch.float32)
        
        if mel.dim() == 2:
            mel = mel.unsqueeze(0)
        
        batch_size = mel.shape[0]
        mel_length = mel.shape[2]
        
        mel_input = mel.contiguous()
        
        self.context.set_input_shape("mel", (batch_size, 100, mel_length))
        
        output_shape = tuple(self.context.get_tensor_shape("waveform"))
        output = torch.empty(output_shape, dtype=torch.float32, device=self.device)
        
        self.context.set_tensor_address("mel", int(mel_input.data_ptr()))
        self.context.set_tensor_address("waveform", int(output.data_ptr()))
        
        self.context.execute_async_v3(self.stream.cuda_stream)
        self.stream.synchronize()
        
        return output
    
    def __call__(self, mel: torch.Tensor) -> torch.Tensor:
        return self.decode(mel)


class VocosVocoder:
    def __init__(
        self,
        model_path: Optional[str] = None,
        config_path: Optional[str] = None,
        device: torch.device = torch.device("cuda:0"),
    ):
        self.device = device
        self.model = None
        
        if model_path and config_path:
            self._load_pytorch_model(model_path, config_path)
    
    def _load_pytorch_model(self, model_path: str, config_path: str):
        from vocos import Vocos
        
        self.model = Vocos.from_hparams(config_path)
        state_dict = torch.load(model_path, map_location="cpu", weights_only=True)
        self.model.load_state_dict(state_dict)
        self.model = self.model.eval().to(self.device)
    
    def decode(self, mel: torch.Tensor) -> torch.Tensor:
        if self.model is None:
            raise RuntimeError("Vocos model not loaded")
        
        mel = mel.to(self.device)
        
        with torch.no_grad():
            waveform = self.model.decode(mel)
        
        return waveform
    
    def __call__(self, mel: torch.Tensor) -> torch.Tensor:
        return self.decode(mel)
