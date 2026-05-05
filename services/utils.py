"""
Utility functions for DUBU journaling automation.
"""

import logging
import sys
from datetime import datetime


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Suppress verbose logs from external libraries
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("msgraph").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
