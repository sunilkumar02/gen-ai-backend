# AI Chatbot Backend

A simple FastAPI backend for a chatbot API.

## Requirements

- Python 3.11+
- `pip`

## Install

```bash
python -m pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Docker

Build the Docker image:

```bash
docker compose build
```

Start the app using Docker Compose:

```bash
docker compose up
```

The FastAPI app will be available at `http://localhost:8000` and the automatic docs at `http://localhost:8000/docs`.

## API

### POST /chat

Request body:

```json
{
  "prompt": "Hello, how are you?",
  "model": "gpt-4"
}
```

Response:

```json
{
  "prompt": "Hello, how are you?",
  "model": "gpt-4",
  "response": "This is a generated reply from the chatbot backend."
}
```
# Gen-ai-backend
