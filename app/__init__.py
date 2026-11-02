import logging
import os

from flask import Flask
from sqlalchemy import create_engine, text

from app import payments
from app.auth import login_manager
from app.db import db_session


def create_app() -> Flask:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    app = Flask(__name__)
    app.config["PAYMENT_WEBHOOK_SECRET"] = os.environ["PAYMENT_WEBHOOK_SECRET"]
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    db_session.configure(bind=engine)
    login_manager.init_app(app)
    app.register_blueprint(payments.bp)

    @app.teardown_appcontext
    def remove_session(exception: BaseException | None) -> None:
        db_session.remove()

    @app.get("/health")
    def health():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app
