import os
import logging
import asyncio
import anthropic

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_anthropic_api():
    """
    Test the Anthropic API with Claude 3.7 Sonnet and extended thinking.
    """
    try:
        # Initialize the Anthropic client
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.error("ANTHROPIC_API_KEY environment variable not set")
            return
        
        client = anthropic.AsyncAnthropic(api_key=api_key)
        
        # Test with Claude 3.7 Sonnet and extended thinking
        logger.info("Testing Claude 3.7 Sonnet model with extended thinking...")
        
        response = await client.messages.create(
            model="claude-3-7-sonnet-20250219",
            max_tokens=4000,
            thinking={
                "type": "enabled",
                "budget_tokens": 3000
            },
            messages=[{
                "role": "user",
                "content": "Are there an infinite number of prime numbers such that n mod 4 == 3?"
            }]
        )
        
        # Log response structure to understand its format
        logger.info(f"Response type: {type(response)}")
        logger.info(f"Response attributes: {dir(response)}")
        
        # Extract and display the content
        content = ""
        if hasattr(response, 'content'):
            if isinstance(response.content, list):
                for block in response.content:
                    if hasattr(block, 'type') and block.type == "text":
                        content += block.text
            else:
                content = response.content
                
        logger.info(f"Content length: {len(content)}")
        logger.info(f"Content (first 200 chars): {content[:200]}...")
        
        # Test if we can also get extended thinking
        if hasattr(response, 'thinking'):
            logger.info("Extended thinking available in response")
            logger.info(f"Thinking type: {type(response.thinking)}")
            logger.info(f"Thinking attributes: {dir(response.thinking)}")
            logger.info(f"Thinking preview: {str(response.thinking)[:200]}...")
            
        return True
    except Exception as e:
        logger.error(f"Error testing Anthropic API: {str(e)}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_anthropic_api())
    if result:
        logger.info("Anthropic API test successful!")
    else:
        logger.error("Anthropic API test failed!")