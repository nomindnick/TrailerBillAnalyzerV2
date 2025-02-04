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

        # Test with a simple completion
        response = client.chat.completions.create(
            model="gpt-4",  # Using a standard model
            messages=[
                {"role": "user", "content": "Say hello"}
            ],
            max_tokens=10
        )

        logger.info(f"Response: {response.choices[0].message.content}")
        return True

    except Exception as e:
        logger.error(f"Error testing OpenAI connection: {str(e)}")
        logger.exception("Full traceback:")
        return False

if __name__ == "__main__":
    test_openai_connection()