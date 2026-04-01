"""Agent definition for the bidi-workshop."""

import os

from google.adk.agents import Agent
from google.adk.tools import google_search

# モデルは環境変数で指定可能（デフォルトはモードに応じて自動選択）
# DIRECT_MODE=TRUE → gemini-3.1-flash-live-preview (genai SDK 直接接続)
# それ以外 → バックエンドに応じて自動選択
#   Vertex AI: gemini-live-2.5-flash-native-audio
#   Gemini API: gemini-2.5-flash-native-audio-preview-12-2025
_direct_mode = os.environ.get("DIRECT_MODE", "FALSE").upper() in ("TRUE", "1")
_use_vertexai = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "TRUE").upper() in ("TRUE", "1")
if _direct_mode:
    _default_model = "gemini-3.1-flash-live-preview"
elif _use_vertexai:
    _default_model = "gemini-live-2.5-flash-native-audio"
else:
    _default_model = "gemini-2.5-flash-native-audio-preview-12-2025"
_model = os.environ.get("GEMINI_MODEL", _default_model)

# Define the agent
agent = Agent(
    name="gal",
    model=_model,
    instruction="""You are a helpful AI assistant.

    You can use Google Search to find current information.
    Like young Japanese women, I speak in a casual tone without using honorifics.
    It's okay if some expressions are a little rude.
    """,
    tools=[google_search],
)
