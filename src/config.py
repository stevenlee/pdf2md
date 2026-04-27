from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import os

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM Provider (Legacy global setting)
    LLM_PROVIDER: str = "ollama"

    # vLLM
    VLLM_API_BASE: str = "http://192.168.1.103:9000/v1"
    VLLM_MODEL: str = "openai/gpt-oss-20b"
    VLLM_API_KEY: str = "dummy-token"

    # Ollama
    OLLAMA_API_BASE: str = "http://192.168.1.103:11434/v1"
    OLLAMA_MODEL_TEXT: str = "qwen3.6:latest"
    OLLAMA_MODEL_VISION: str = "gemma4:26b"
    OLLAMA_MODEL_OCR: str = "glm-ocr:latest"

    # 路由設定
    TEXT_PROVIDER: str = "vllm"        # 文字任務由 vLLM 處理 (gpt-oss-20b)
    VISION_PROVIDER: str = "ollama"    # 視覺任務由 Ollama 處理 (gemma4)
    OCR_PROVIDER: str = "ollama"      # OCR 任務由 Ollama 處理 (glm-ocr)

    # Gemini
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # App Settings
    INPUT_DIR: str = "input_dir"
    OUTPUT_DIR: str = "output_dir"

settings = Settings()
