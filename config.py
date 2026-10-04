from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_id: int
    database_path: Path
    photos_dir: Path
    required_channel: str
    required_channel_url: str
    payout_channel: str
    min_withdraw: float
    task_reward: float
    referral_reward: float
    ad_api_token: str
    flyer_api_key: str
    log_level: str


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or "replace_with" in token:
        raise ValueError("Укажите действительный BOT_TOKEN в файле .env")
    return Config(
        bot_token=token,
        admin_id=int(os.getenv("ADMIN_ID", "391992084")),
        database_path=Path(os.getenv("DATABASE_PATH", "data/bot.sqlite3")),
        photos_dir=Path(os.getenv("PHOTOS_DIR", "data/photos")),
        required_channel=os.getenv("REQUIRED_CHANNEL", "").strip(),
        required_channel_url=os.getenv("REQUIRED_CHANNEL_URL", "").strip(),
        payout_channel=os.getenv("PAYOUT_CHANNEL", "").strip(),
        min_withdraw=float(os.getenv("MIN_WITHDRAW", "5")),
        task_reward=float(os.getenv("TASK_REWARD", "0.5")),
        referral_reward=float(os.getenv("REFERRAL_REWARD", "0.5")),
        ad_api_token=os.getenv("AD_API_TOKEN", "").strip(),
        flyer_api_key=os.getenv("FLYER_API_KEY", "").strip(),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )