import logging
import sys
from app.core.config import settings

def setup_logging():
    level = logging.INFO
    if settings.environment == "dev":
        level = logging.DEBUG
        
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Create logger instance
    logger = logging.getLogger("medical_ops")
    return logger

logger = setup_logging()
