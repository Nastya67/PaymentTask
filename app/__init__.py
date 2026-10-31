import os

from flask import Flask
from sqlalchemy import create_engine, text


def create_app() -> Flask:
    app = Flask(__name__)
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    app.extensions["engine"] = engine

    @app.get("/health")
    def health():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app
