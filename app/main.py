from fastapi import FastAPI

from app.router.auth import router as auth_router
from app.router.chat import router as chat_router
from app.router.errors import ERROR_RESPONSES, configure_api
from app.router.infra import router as infra_router
from app.router.users import router as users_router
from app.router.thread import router as thread_router

app = FastAPI(
    title="AI Chatbot",
    description="A simple AI chatbot using LangChain and OpenAI.",
    version="1.0.0",
    responses=ERROR_RESPONSES,
)
configure_api(app)

app.include_router(infra_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(chat_router)
app.include_router(thread_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
