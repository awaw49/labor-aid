import os

from . import settings as settings_store

LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "120"))
ASR_MODEL = os.environ.get("ASR_MODEL", "small")
ASR_DEVICE = os.environ.get("ASR_DEVICE", "cpu")
CITY_ID = os.environ.get("CITY_ID", "hangzhou")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
MAX_UPLOAD_BYTES = 12 * 1024 * 1024


def llm():
    return settings_store.load()
