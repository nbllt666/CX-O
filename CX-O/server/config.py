import json
import os
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8100


@dataclass
class ASRConfig:
    model_dir: str = "SenseVoice"
    device: str = "cuda"
    enabled: bool = True
    language: str = "auto"
    use_itn: bool = True


@dataclass
class TTSConfig:
    model_dir: str = "F5-TTS"
    device: str = "cuda"
    enabled: bool = True
    ref_audio: str = ""
    ref_text: str = ""
    speed: float = 1.0


@dataclass
class LLMConfig:
    provider: str = "ollama"
    host: str = "http://localhost:11434"
    model: str = "qwen3-vl:8b"
    temperature: float = 0.7
    max_tokens: int = 4096


@dataclass
class MemoryConfig:
    vector_enabled: bool = True
    vector_backend: str = "milvus_lite"
    db_path: str = "data/memories.db"
    chroma_db_path: str = "data/chroma"
    chroma_collection: str = "memories"
    chroma_vector_size: int = 1024


@dataclass
class CorsConfig:
    enabled: bool = True
    origins: list = field(default_factory=lambda: ["*"])
    allow_credentials: bool = True


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/app.log"
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 5


@dataclass
class DatabaseConfig:
    memories_db: str = "data/memories.db"
    sessions_db: str = "data/sessions.db"
    acp_db: str = "data/acp"


@dataclass
class ACPConfig:
    agent_id: str = "default"
    agent_name: str = "CX-O Agent"
    enabled: bool = True


class Config:
    _instance: Optional["Config"] = None

    def __init__(self):
        self.server = ServerConfig()
        self.asr = ASRConfig()
        self.tts = TTSConfig()
        self.llm = LLMConfig()
        self.memory = MemoryConfig()
        self.cors = CorsConfig()
        self.logging = LoggingConfig()
        self.database = DatabaseConfig()
        self.acp = ACPConfig()

    @classmethod
    def get_instance(cls) -> "Config":
        if cls._instance is None:
            cls._instance = cls()
            cls._instance.load()
        return cls._instance

    def load(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.environ.get(
                "CX_O_CONFIG",
                str(Path(__file__).parent.parent / "config.json")
            )

        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._apply_dict(data)

    def _apply_dict(self, data: dict):
        section_map = {
            "server": self.server,
            "asr": self.asr,
            "tts": self.tts,
            "llm": self.llm,
            "memory": self.memory,
            "cors": self.cors,
            "logging": self.logging,
            "database": self.database,
            "acp": self.acp,
        }

        for key, section in section_map.items():
            if key in data:
                section_data = data[key]
                if isinstance(section_data, dict):
                    for attr, value in section_data.items():
                        if hasattr(section, attr):
                            setattr(section, attr, value)

    def to_dict(self) -> dict:
        return {
            "server": {
                "host": self.server.host,
                "port": self.server.port,
            },
            "asr": {
                "model_dir": self.asr.model_dir,
                "device": self.asr.device,
                "enabled": self.asr.enabled,
                "language": self.asr.language,
                "use_itn": self.asr.use_itn,
            },
            "tts": {
                "model_dir": self.tts.model_dir,
                "device": self.tts.device,
                "enabled": self.tts.enabled,
                "ref_audio": self.tts.ref_audio,
                "ref_text": self.tts.ref_text,
                "speed": self.tts.speed,
            },
            "llm": {
                "provider": self.llm.provider,
                "host": self.llm.host,
                "model": self.llm.model,
                "temperature": self.llm.temperature,
                "max_tokens": self.llm.max_tokens,
            },
            "memory": {
                "vector_enabled": self.memory.vector_enabled,
                "vector_backend": self.memory.vector_backend,
                "db_path": self.memory.db_path,
                "chroma_db_path": self.memory.chroma_db_path,
                "chroma_collection": self.memory.chroma_collection,
                "chroma_vector_size": self.memory.chroma_vector_size,
            },
            "cors": {
                "enabled": self.cors.enabled,
                "origins": self.cors.origins,
                "allow_credentials": self.cors.allow_credentials,
            },
            "logging": {
                "level": self.logging.level,
                "file": self.logging.file,
                "max_bytes": self.logging.max_bytes,
                "backup_count": self.logging.backup_count,
            },
            "database": {
                "memories_db": self.database.memories_db,
                "sessions_db": self.database.sessions_db,
                "acp_db": self.database.acp_db,
            },
            "acp": {
                "agent_id": self.acp.agent_id,
                "agent_name": self.acp.agent_name,
                "enabled": self.acp.enabled,
            },
        }


_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config.get_instance()
    return _config


def load_config(config_path: Optional[str] = None) -> Config:
    global _config
    _config = Config()
    _config.load(config_path)
    return _config
