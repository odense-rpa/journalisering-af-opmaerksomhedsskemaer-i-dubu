"""
Utility functions for DUBU journaling automation.
"""
import logging
import sys
from datetime import datetime

from config import settings


def setup_logging():
    """Setup logging configuration."""
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    
    # Suppress verbose logs from external libraries
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("msgraph").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def calculate_age_from_cpr(cpr_nr: str) -> int:
    """
    Calculate age from Danish CPR number.
    CPR format: DDMMYY + 4 digits (where YY is century digit dependent)
    """
    if not cpr_nr or len(cpr_nr) < 6:
        return -1
    
    try:
        day = int(cpr_nr[0:2])
        month = int(cpr_nr[2:4])
        year = int(cpr_nr[4:6])
        
        # Determine century based on CPR 10th digit (century digit)
        if len(cpr_nr) >= 10:
            century_digit = int(cpr_nr[9])
            # 0-36 = 2000s, 37-99 = 1900s (common rule)
            if century_digit <= 3:
                year += 2000
            else:
                year += 1900
        else:
            # Default: if year > current year mod 100, assume 1900s, else 2000s
            current_year = datetime.now().year
            if year > current_year % 100:
                year += 1900
            else:
                year += 2000
        
        birth_date = datetime(year, month, day)
        age = (datetime.now() - birth_date).days // 365
        return age
    except (ValueError, IndexError):
        return -1
