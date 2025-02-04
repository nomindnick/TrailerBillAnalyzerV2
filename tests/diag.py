import sys
import pkg_resources
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_diagnostics():
    # Python version
    logger.info(f"Python version: {sys.version}")

    # OpenAI and related packages
    packages_to_check = ['openai', 'httpx', 'pydantic', 'typing-extensions']
    for package in packages_to_check:
        try:
            version = pkg_resources.get_distribution(package).version
            logger.info(f"{package} version: {version}")
        except pkg_resources.DistributionNotFound:
            logger.warning(f"{package} not found")

    # Check environment variables (without printing actual values)
    logger.info("Checking OPENAI_API_KEY...")
    api_key = os.getenv('OPENAI_API_KEY')
    if api_key:
        logger.info("OPENAI_API_KEY is set")
        logger.info(f"API key starts with: {api_key[:7]}...")
        logger.info(f"API key length: {len(api_key)}")
    else:
        logger.warning("OPENAI_API_KEY is not set")

    # Check Python path
    logger.info("Python path:")
    for path in sys.path:
        logger.info(f"  {path}")

if __name__ == "__main__":
    run_diagnostics()