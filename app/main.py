import os
import logging
from dotenv import load_dotenv

from fastapi import FastAPI, APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.database import engine
from app.api.users import router as users_router
from app.api.auth import router as auth_router
from app.api.errors import ERROR_RESPONSES, configure_api

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from app.config.prompt.system_prompt import SYSTEM_PROMPT

load_dotenv()

logger = logging.getLogger(__name__)

openai_api_key = os.getenv("OPENAI_API_KEY")
groq_api_key = os.getenv("GROQ_API_KEY")

app = FastAPI(title="AI Chatbot", description="A simple AI chatbot using LangChain and Groq.", version="1.0.0", responses=ERROR_RESPONSES)
configure_api(app)
router = APIRouter(prefix="/invoke")

app.include_router(router)
app.include_router(users_router)
app.include_router(auth_router)

model = (
    ChatOpenAI(model_name="gpt-6-luna", openai_api_key=openai_api_key)
    if openai_api_key
    else None
)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/health/db")
async def database_health():
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("Database health check failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from exc

    return {"status": "ok", "database": "reachable"}

@app.post("/chat")
async def chat(input: str):
    if model is None:
        raise HTTPException(
            status_code=503,
            detail="Chat service is not configured. Set OPENAI_API_KEY and restart the backend.",
        )

    prompt_template = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "{input}"),
    ])

    parsed = StrOutputParser()

    response = prompt_template | model | parsed

    return {"response":  response.invoke({"input": input})}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
