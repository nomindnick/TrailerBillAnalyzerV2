import os
import logging
from typing import List

logger = logging.getLogger(__name__)

def check_environment_variables(required_vars: List[str]) -> bool:
    """
    Check if all required environment variables are set.

    Args:
        required_vars: List of required environment variable names

    Returns:
        bool: True if all variables are set, False otherwise
    """
    missing_vars = []

    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)

    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return False

    logger.info("All required environment variables are set")
    return True

def get_openai_key() -> str:
    """
    Get OpenAI API key with validation.

    Returns:
        str: The API key

    Raises:
        ValueError: If API key is not set
    """
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        logger.error("OPENAI_API_KEY environment variable is not set")
        raise ValueError("OPENAI_API_KEY environment variable is not set")

    # Basic validation of key format
    if not api_key.startswith('sk-'):
        logger.warning("OPENAI_API_KEY does not follow expected format (should start with 'sk-')")

    return api_key