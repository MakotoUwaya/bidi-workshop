# bidi-workshop

Google ADK (Agent Development Kit) と Gemini Live API を使った双方向ストリーミングワークショップです。

## 前提条件

以下のツールを事前にインストールしてください。

| ツール | バージョン | 用途 |
|--------|-----------|------|
| [Python](https://www.python.org/) | 3.10 以上 | ランタイム |
| [uv](https://docs.astral.sh/uv/) | 最新 | Python パッケージマネージャー |
| [Google Cloud CLI (gcloud)](https://cloud.google.com/sdk/docs/install) | 最新 | GCP 認証・API 有効化 |

Chrome ブラウザ（マイク・ウェブカメラ付き）を推奨します。

## Google Cloud プロジェクト設定

### 1. プロジェクトの準備

課金が有効な Google Cloud プロジェクトが必要です。
プロジェクト ID は [Cloud Console](https://console.cloud.google.com/) のダッシュボードで確認できます。

### 2. gcloud 認証

```bash
gcloud auth login
gcloud auth application-default login
```

### 3. Vertex AI API の有効化

```bash
gcloud services enable aiplatform.googleapis.com --project=<YOUR_PROJECT_ID>
```

## セットアップ

### 1. 環境変数の設定

テンプレートをコピーして `.env` ファイルを作成します。

```bash
cd app
cp .env.template .env
```

`.env` を編集し、自分のプロジェクト ID を設定してください。

```dotenv
GOOGLE_CLOUD_PROJECT=your_project_id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_GENAI_USE_VERTEXAI=TRUE
```

### 2. Python 依存関係のインストール

```bash
uv sync
```

## 起動

```bash
uv run uvicorn app.main:app --reload
```

ブラウザで http://localhost:8000 にアクセスしてください。

## プロジェクト構成

```
bidi-workshop/
├── pyproject.toml          # プロジェクト定義・依存関係
└── app/
    ├── .env.template       # 環境変数テンプレート
    ├── main.py             # FastAPI サーバー (WebSocket + ADK)
    ├── my_agent/
    │   ├── __init__.py
    │   └── agent.py        # エージェント定義
    └── static/
        ├── index.html
        ├── css/style.css
        └── js/             # フロントエンドスクリプト
```
