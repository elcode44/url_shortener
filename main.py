from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.routes import router
from db.database import Database


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Server started — docs at http://localhost:8000/docs")
    yield
    db.close()
    print("Server shutting down")


app = FastAPI(
    title="URL Shortener",
    description="A fast URL shortening service with caching and analytics",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)
