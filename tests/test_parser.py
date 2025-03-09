import logging
from src.services.base_parser import BaseParser

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test if the BaseParser can be imported and instantiated 
def test_parser():
    logger.info("Testing BaseParser import and instantiation")
    try:
        parser = BaseParser()
        logger.info("BaseParser successfully imported and instantiated")
        return True
    except Exception as e:
        logger.error(f"Error importing or instantiating BaseParser: {str(e)}")
        return False

if __name__ == "__main__":
    success = test_parser()
    print(f"Test passed: {success}")