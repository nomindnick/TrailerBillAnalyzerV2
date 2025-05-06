import os
from openai import OpenAI
import logging
from httpx import Client

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_openai_connection():
    try:
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")

        # Create client with default settings
        client = OpenAI()

        # Test with a simple completion for gpt-4.1 (can use more parameters)
        logger.info("Testing GPT-4.1 model...")
        response1 = client.chat.completions.create(
            model="gpt-4.1-2025-04-14",
            messages=[
                {"role": "user", "content": "Say hello"}
            ],
            temperature=0.1  # GPT-4.1 supports temperature
        )
        logger.info(f"GPT-4.1 Response: {response1.choices[0].message.content}")

        # Test o4-mini model with absolute minimal parameters
        logger.info("Testing o4-mini model...")
        response2 = client.chat.completions.create(
            model="o4-mini-2025-04-16",
            messages=[
                {"role": "user", "content": "Say hello"}
            ]
            # No additional parameters for maximum compatibility
        )
        logger.info(f"o4-mini Response: {response2.choices[0].message.content}")

        return True

    except Exception as e:
        logger.error(f"Error testing OpenAI connection: {str(e)}")
        logger.exception("Full traceback:")
        return False

if __name__ == "__main__":
    test_openai_connection()