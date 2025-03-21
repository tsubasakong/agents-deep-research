import os
from openai import AsyncOpenAI
from agents import OpenAIChatCompletionsModel, OpenAIResponsesModel
from dotenv import load_dotenv

load_dotenv(override=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

DEFAULT_REASONING_PROVIDER=os.getenv("DEFAULT_REASONING_PROVIDER", "openai")
DEFAULT_REASONING_MODEL=os.getenv("DEFAULT_REASONING_MODEL", "o3-mini")
MAIN_MODEL_PROVIDER=os.getenv("MAIN_MODEL_PROVIDER", "openai")
MAIN_MODEL=os.getenv("MAIN_MODEL", "gpt-4o")
FAST_MODEL_PROVIDER=os.getenv("FAST_MODEL_PROVIDER", "openai")
FAST_MODEL=os.getenv("FAST_MODEL", "gpt-4o-mini")

supported_providers = ["openai", "deepseek", "openrouter"]
provider_mapping = {
    "openai": {
        "model": OpenAIResponsesModel,
        "base_url": None,
        "api_key": OPENAI_API_KEY,
    },
    "deepseek": {
        "model": OpenAIChatCompletionsModel,
        "base_url": "https://api.deepseek.com/v1",
        "api_key": DEEPSEEK_API_KEY,
    },
    "openrouter": {
        "model": OpenAIChatCompletionsModel,
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": OPENROUTER_API_KEY,
    },
}

if DEFAULT_REASONING_PROVIDER not in supported_providers:
    raise ValueError(f"Invalid model provider: {DEFAULT_REASONING_PROVIDER}")
if MAIN_MODEL_PROVIDER not in supported_providers:
    raise ValueError(f"Invalid model provider: {MAIN_MODEL_PROVIDER}")
if FAST_MODEL_PROVIDER not in supported_providers:
    raise ValueError(f"Invalid model provider: {FAST_MODEL_PROVIDER}")

if OPENAI_API_KEY:
    from agents import set_tracing_export_api_key
    set_tracing_export_api_key(OPENAI_API_KEY)

# ------- SET UP REASONING MODEL -------

reasoning_client = AsyncOpenAI(
    api_key=provider_mapping[DEFAULT_REASONING_PROVIDER]["api_key"],
    base_url=provider_mapping[DEFAULT_REASONING_PROVIDER]["base_url"],
)

reasoning_model = provider_mapping[DEFAULT_REASONING_PROVIDER]["model"](
    model=DEFAULT_REASONING_MODEL,
    openai_client=reasoning_client
)

# ------- SET UP MAIN MODEL -------

main_client = AsyncOpenAI(
    api_key=provider_mapping[MAIN_MODEL_PROVIDER]["api_key"],
    base_url=provider_mapping[MAIN_MODEL_PROVIDER]["base_url"],
)

main_model = provider_mapping[MAIN_MODEL_PROVIDER]["model"](
    model=MAIN_MODEL,
    openai_client=main_client
)

# ------- SET UP FAST MODEL -------

fast_client = AsyncOpenAI(
    api_key=provider_mapping[FAST_MODEL_PROVIDER]["api_key"],
    base_url=provider_mapping[FAST_MODEL_PROVIDER]["base_url"],
)

fast_model = provider_mapping[FAST_MODEL_PROVIDER]["model"](
    model=FAST_MODEL,
    openai_client=fast_client
)

__all__ = ["reasoning_model", "main_model", "fast_model"]
