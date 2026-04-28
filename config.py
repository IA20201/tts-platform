from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mimo_api_key: str
    mimo_base_url: str = "https://api.xiaomimimo.com/v1"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "mimo-v2.5"
    tts_model: str = "mimo-v2.5-tts"
    default_voice: str = "Chloe"
    max_concurrency: int = 10
    max_chunk_chars: int = 500
    retry_max: int = 3
    retry_delay: float = 1.0
    output_dir: str = "output"
    voices_db_path: str = "voice_lab/voices.json"

    class Config:
        env_file = ".env"


# 内置音色列表
BUILT_IN_VOICES = {
    "mimo-v2.5-tts": [
        "mimo_default", "冰糖", "茉莉", "苏打", "白桦",
        "Mia", "Chloe", "Milo", "Dean",
    ],
    "mimo-v2-tts": ["mimo_default", "default_en", "default_zh"],
}
