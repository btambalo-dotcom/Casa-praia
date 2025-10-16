
import os
from dotenv import load_dotenv

load_dotenv()

def get_database_url():
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    # Render detection
    if os.getenv("RENDER", "false").lower() == "true" or os.getenv("RENDER_EXTERNAL_URL"):
        return "sqlite:////tmp/app.db"
    return "sqlite:///app.db"

from flask import Flask
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = get_database_url()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")

print(f"Banco em uso: {app.config['SQLALCHEMY_DATABASE_URI']}")
