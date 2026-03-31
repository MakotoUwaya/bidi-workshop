# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Google ADK (Agent Development Kit) と Gemini Live API を使った双方向音声/テキスト/画像ストリーミングのワークショップ。
FastAPI + WebSocket バックエンドと、Vanilla JS フロントエンドで構成される。

## Commands

```bash
# 依存関係インストール
uv sync

# サーバー起動
uv run uvicorn app.main:app --reload
```

## Architecture

### バックエンド（FastAPI + ADK）

- `app/main.py` - FastAPI サーバー。WebSocket で ADK Runner と双方向ストリーミング
- `app/my_agent/agent.py` - ADK Agent 定義（モデル: `gemini-live-2.5-flash-native-audio`、ツール: `google_search`）

**WebSocket エンドポイント:** `/ws/{user_id}/{session_id}`
- Upstream: クライアント→エージェント（テキスト JSON / バイナリ PCM 音声 / base64 画像）
- Downstream: エージェント→クライアント（ADK Event JSON）
- `asyncio.gather()` で双方向を並行処理

### フロントエンド（static/）

- `app/static/js/app.js` - WebSocket 通信、イベントパース、メッセージ描画、音声制御
- `app/static/js/audio-recorder.js` / `pcm-recorder-processor.js` - AudioWorklet 録音（16kHz mono）
- `app/static/js/audio-player.js` / `pcm-player-processor.js` - AudioWorklet 再生（24kHz）

### 重要な注意点

- `.env` の `load_dotenv()` は ADK の agent import **より前**に実行する必要がある（ADK が環境変数を読む）
- セッションは `InMemorySessionService` で管理（再起動で消える）
