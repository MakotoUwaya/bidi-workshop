"""Agent definition for the bidi-workshop."""

from google.adk.agents import Agent
from google.adk.tools import google_search

# Define the agent
agent = Agent(
    name="gal",
    # Vertex AI / Gemini AI Studio 両方で使えるモデルはこれ
    # 3/26 に最新のモデルが発表されたので、切り替えれば使える(Vertex AI は4月頃予定)
    # Native Audio Model は音声のバイナリデータを直接理解して、解釈して、直接レスポンスする
    # Google のユニークな技術(遅延が少なく、自然なトーン、感情的対話、直接音の波形を認識する)
    # ツールの実行が2回行われたりすることがデメリット(確実に1回だけ実行してほしい、というのは苦手)
    # 文字起こし用のモデルも併用していて、文字起こしの精度が低いので誤認識が多い
    model="gemini-live-2.5-flash-native-audio",
    # model="gemini-3.1-flash-live-preview",
    instruction="""You are a helpful AI assistant.

    You can use Google Search to find current information.
    Like young Japanese women, I speak in a casual tone without using honorifics.
    It's okay if some expressions are a little rude.
    """,
    tools=[google_search],
)
