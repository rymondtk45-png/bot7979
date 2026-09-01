import logging

from src.config import CONFIG
from src.engine import SignalEngine
from src.logger import setup_logging


def main() -> None:
    setup_logging(CONFIG.LOG_PATH)
    logging.info("Starting signal aggregation bot")
    engine = SignalEngine()
    engine.run()


if __name__ == "__main__":
    main()
