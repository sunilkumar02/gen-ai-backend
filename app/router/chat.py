import os

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.config.prompt.system_prompt import SYSTEM_PROMPT

load_dotenv()

router = APIRouter(tags=["Chat"])
openai_api_key = os.getenv("OPENAI_API_KEY")

model = (
    ChatOpenAI(model_name="gpt-6-luna", openai_api_key=openai_api_key)
    if openai_api_key
    else None
)


@router.post("/chat")
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

