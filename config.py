import os

from dotenv import load_dotenv

load_dotenv()

PARTNER_API_KEY = os.getenv("PARTNER_API_KEY") or "zxc_demo_FAKE_KEY_9f3a7c21e8b44d0a_DO_NOT_USE"  # INTENTIONAL VULNERABILITY FOR DEMO
