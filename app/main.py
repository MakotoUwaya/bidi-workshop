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
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Suppress noisy warnings
warnings.filterwarnings("ignore", message="Your application has authenticated using end user credentials")
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

load_dotenv(Path(__file__).parent / ".env")

from my_agent.agent import agent  # noqa: E402

APP_NAME = "bidi-workshop"

# Logging setup: set LOG_LEVEL=DEBUG to see audio chunk logs
log_level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(level=log_level, format="%(message)s")
logger = logging.getLogger(__name__)


app = FastAPI()
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

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

    # Build speech config from query parameter
    speech_config = None
    voice_name = voice or None
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
        """Receives messages from WebSocket and sends to LiveRequestQueue."""
        while True:
            message = await websocket.receive()

            # Handle text messages (JSON)
            if "text" in message:
                json_message = json.loads(message["text"])

                # Handle text messages
                if json_message.get("type") == "text":
                    user_text = json_message["text"]
                    logger.info("[UPSTREAM] Text: %s", user_text)

                    content = types.Content(
                        parts=[types.Part(text=user_text)]
                    )
                    live_request_queue.send_content(content)

                # Handle image messages
                elif json_message.get("type") == "image":
                    logger.info("[UPSTREAM] Image received")

                    # Decode base64 image data
                    image_data = base64.b64decode(json_message["data"])
                    mime_type = json_message.get("mimeType", "image/jpeg")

                    logger.info("[UPSTREAM] Image: %d bytes, %s", len(image_data), mime_type)

                    # Create image blob and send
                    image_blob = types.Blob(
                        mime_type=mime_type,
                        data=image_data
                    )
                    live_request_queue.send_realtime(image_blob)

            # Handle binary messages (audio)
            elif "bytes" in message:
                audio_data = message["bytes"]
                logger.debug("[UPSTREAM] Audio chunk: %d bytes", len(audio_data))

                audio_blob = types.Blob(
                    mime_type="audio/pcm;rate=16000",
                    data=audio_data
                )
                live_request_queue.send_realtime(audio_blob)

    async def downstream_task() -> None:
        """Receives Events from run_live() and sends to WebSocket."""
        logger.info("[DOWNSTREAM] Starting run_live()")
        speaker_info_sent = False

        async for event in runner.run_live(
            user_id=user_id,
            session_id=session_id,
            live_request_queue=live_request_queue,
            run_config=run_config,
        ):
            # Send speaker info once Gemini live connection is established
            if not speaker_info_sent:
                await websocket.send_json({
                    "type": "speaker_info",
                    "voice_name": voice_name,
                    "agent_name": agent.name,
                })
                speaker_info_sent = True

            event_json = event.model_dump_json(exclude_none=True, by_alias=True)
            # Audio events are high-volume, log at DEBUG
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
            # Notify client so it triggers a full reconnect
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
