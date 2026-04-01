"""ADK Gemini Live API bidirectional streaming server."""

import asyncio
import base64
import json
import logging
import os
import warnings
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.genai import types

# Suppress noisy warnings
warnings.filterwarnings("ignore", message="Your application has authenticated using end user credentials")
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

load_dotenv(Path(__file__).parent / ".env")

from my_agent.agent import agent  # noqa: E402

APP_NAME = "bidi-workshop"
_direct_mode = os.environ.get("DIRECT_MODE", "FALSE").upper() in ("TRUE", "1")
_use_vertexai = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "TRUE").upper() in ("TRUE", "1")

# Logging setup: set LOG_LEVEL=DEBUG to see audio chunk logs
log_level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(level=log_level, format="%(message)s")
logger = logging.getLogger(__name__)


app = FastAPI()
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

if _direct_mode:
    # Direct genai SDK mode (Gemini API + 3.1 model)
    from google import genai

    _genai_client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))
else:
    # ADK mode (Vertex AI or Gemini API)
    from google.adk.agents.live_request_queue import LiveRequestQueue
    from google.adk.agents.run_config import RunConfig, StreamingMode
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    session_service = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_service)


@app.get("/")
async def root():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.websocket("/ws/{user_id}/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str,
    session_id: str,
    voice: str = Query(default=""),
) -> None:
    await websocket.accept()
    logger.info("Connection open")

    voice_name = voice or None

    if _direct_mode:
        await _handle_direct_session(websocket, voice_name)
    else:
        await _handle_adk_session(websocket, user_id, session_id, voice_name)


async def _handle_adk_session(
    websocket: WebSocket, user_id: str, session_id: str, voice_name: str | None
) -> None:
    """ADK Runner 経由の双方向ストリーミング (Vertex AI)."""
    speech_config = None
    if voice_name:
        speech_config = types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=voice_name,
                )
            )
        )

    run_config = RunConfig(
        speech_config=speech_config,
        streaming_mode=StreamingMode.BIDI,
        response_modalities=["AUDIO"],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        # Vertex AI では透過的セッション再開を有効化（履歴テキスト再送を回避）
        session_resumption=(
            types.SessionResumptionConfig(transparent=True)
            if _use_vertexai else None
        ),
    )

    session = await session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if not session:
        await session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )

    live_request_queue = LiveRequestQueue()

    async def upstream_task() -> None:
        while True:
            message = await websocket.receive()

            if "text" in message:
                json_message = json.loads(message["text"])

                if json_message.get("type") == "text":
                    user_text = json_message["text"]
                    logger.info("[UPSTREAM] Text: %s", user_text)
                    content = types.Content(parts=[types.Part(text=user_text)])
                    live_request_queue.send_content(content)

                elif json_message.get("type") == "image":
                    logger.info("[UPSTREAM] Image received")
                    image_data = base64.b64decode(json_message["data"])
                    mime_type = json_message.get("mimeType", "image/jpeg")
                    logger.info("[UPSTREAM] Image: %d bytes, %s", len(image_data), mime_type)
                    image_blob = types.Blob(mime_type=mime_type, data=image_data)
                    live_request_queue.send_realtime(image_blob)

            elif "bytes" in message:
                audio_data = message["bytes"]
                logger.debug("[UPSTREAM] Audio chunk: %d bytes", len(audio_data))
                audio_blob = types.Blob(mime_type="audio/pcm;rate=16000", data=audio_data)
                live_request_queue.send_realtime(audio_blob)

    async def downstream_task() -> None:
        logger.info("[DOWNSTREAM] Starting run_live()")
        speaker_info_sent = False

        async for event in runner.run_live(
            user_id=user_id,
            session_id=session_id,
            live_request_queue=live_request_queue,
            run_config=run_config,
        ):
            if not speaker_info_sent:
                await websocket.send_json({
                    "type": "speaker_info",
                    "voice_name": voice_name,
                    "agent_name": agent.name,
                })
                speaker_info_sent = True

            event_json = event.model_dump_json(exclude_none=True, by_alias=True)
            if '"inlineData"' in event_json:
                logger.debug("[DOWNSTREAM] Audio event: %s...", event_json[:80])
            else:
                logger.info("[DOWNSTREAM] Event: %s...", event_json[:200])
            await websocket.send_text(event_json)

        logger.info("[DOWNSTREAM] run_live() completed")

    try:
        await asyncio.gather(upstream_task(), downstream_task())
    except (WebSocketDisconnect, RuntimeError):
        logger.info("Client disconnected")
    except Exception as e:
        if "1000" in str(e):
            logger.info("Gemini session closed, notifying client to reconnect")
            try:
                await websocket.send_json({"type": "session_expired"})
                await websocket.close()
            except Exception:
                pass
        else:
            logger.error("Unexpected error: %s", e)
    finally:
        live_request_queue.close()
        logger.info("Session terminated")


async def _handle_direct_session(
    websocket: WebSocket, voice_name: str | None
) -> None:
    """genai SDK 直接接続の双方向ストリーミング (Gemini API)."""
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=voice_name or "Aoede",
                )
            )
        ),
        system_instruction=types.Content(
            parts=[types.Part(text=agent.instruction)],
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            turn_coverage="TURN_INCLUDES_ONLY_ACTIVITY",
        ),
        tools=[types.Tool(google_search=types.GoogleSearch())],
    )

    logger.info("Connecting to Gemini Live (direct): model=%s", agent.model)

    try:
        async with _genai_client.aio.live.connect(
            model=agent.model, config=config
        ) as session:
            logger.info("Gemini Live session opened")

            await websocket.send_json({
                "type": "speaker_info",
                "voice_name": voice_name,
                "agent_name": agent.name,
            })

            async def upstream_task() -> None:
                while True:
                    message = await websocket.receive()

                    if "text" in message:
                        json_message = json.loads(message["text"])

                        if json_message.get("type") == "text":
                            user_text = json_message["text"]
                            logger.info("[UPSTREAM] Text: %s", user_text)
                            await session.send_realtime_input(text=user_text)

                        elif json_message.get("type") == "image":
                            logger.info("[UPSTREAM] Image received")
                            image_data = base64.b64decode(json_message["data"])
                            mime_type = json_message.get("mimeType", "image/jpeg")
                            logger.info("[UPSTREAM] Image: %d bytes, %s", len(image_data), mime_type)
                            await session.send_realtime_input(
                                media=types.Blob(mime_type=mime_type, data=image_data)
                            )

                    elif "bytes" in message:
                        audio_data = message["bytes"]
                        logger.debug("[UPSTREAM] Audio chunk: %d bytes", len(audio_data))
                        await session.send_realtime_input(
                            audio=types.Blob(
                                mime_type="audio/pcm;rate=16000",
                                data=audio_data,
                            )
                        )

            async def downstream_task() -> None:
                logger.info("[DOWNSTREAM] Starting receive loop")
                while True:
                    async for response in session.receive():
                        sc = response.server_content
                        if not sc:
                            continue

                        # Audio / text content
                        if sc.model_turn and sc.model_turn.parts:
                            for part in sc.model_turn.parts:
                                if part.inline_data:
                                    audio_b64 = base64.b64encode(part.inline_data.data).decode()
                                    event = {
                                        "content": {
                                            "parts": [{
                                                "inlineData": {
                                                    "mimeType": part.inline_data.mime_type or "audio/pcm",
                                                    "data": audio_b64,
                                                }
                                            }]
                                        },
                                        "partial": True,
                                    }
                                    logger.debug("[DOWNSTREAM] Audio event")
                                    await websocket.send_json(event)

                                elif part.text:
                                    event = {
                                        "content": {"parts": [{"text": part.text}]},
                                        "partial": True,
                                    }
                                    logger.info("[DOWNSTREAM] Text: %s", part.text[:100])
                                    await websocket.send_json(event)

                        # Input transcription (user speech)
                        if sc.input_transcription and sc.input_transcription.text:
                            event = {
                                "inputTranscription": {
                                    "text": sc.input_transcription.text,
                                    "finished": getattr(sc.input_transcription, "finished", False),
                                }
                            }
                            logger.info("[DOWNSTREAM] Input transcription: %s", sc.input_transcription.text)
                            await websocket.send_json(event)

                        # Output transcription (agent speech)
                        if sc.output_transcription and sc.output_transcription.text:
                            event = {
                                "outputTranscription": {
                                    "text": sc.output_transcription.text,
                                    "finished": getattr(sc.output_transcription, "finished", False),
                                }
                            }
                            logger.info("[DOWNSTREAM] Output transcription: %s", sc.output_transcription.text)
                            await websocket.send_json(event)

                        # Turn complete
                        if sc.turn_complete:
                            logger.info("[DOWNSTREAM] Turn complete")
                            await websocket.send_json({"turnComplete": True})

                        # Interrupted
                        if sc.interrupted:
                            logger.info("[DOWNSTREAM] Interrupted")
                            await websocket.send_json({"interrupted": True})

                    logger.debug("[DOWNSTREAM] Receive iterator completed, re-entering")

            await asyncio.gather(upstream_task(), downstream_task())

    except (WebSocketDisconnect, RuntimeError):
        logger.info("Client disconnected")
    except Exception as e:
        if "1000" in str(e):
            logger.info("Gemini session closed, notifying client to reconnect")
            try:
                await websocket.send_json({"type": "session_expired"})
                await websocket.close()
            except Exception:
                pass
        else:
            logger.error("Unexpected error: %s", e)
    finally:
        logger.info("Session terminated")
