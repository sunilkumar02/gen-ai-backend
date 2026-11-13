import os

from dotenv import load_dotenv
from sqlalchemy import URL

load_dotenv()

DATABASE_URL = URL.create(
    drivername="postgresql+asyncpg",
    username=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    host=os.environ["DB_HOST"],
    port=int(os.getenv("DB_PORT", "5432")),
    database=os.environ["DB_NAME"],
)
