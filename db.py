import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()


def get_db():
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        raise RuntimeError("MONGODB_URI is not set")
    client = MongoClient(uri)
    return client["zxc_bank_demo"]


def get_transfers():
    return get_db()["transfers"]
