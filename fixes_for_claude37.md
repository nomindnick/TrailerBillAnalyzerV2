# Claude 3.7 Extended Thinking Fix

## Changes Made

1. **Updated Anthropic SDK Version**
   - Changed from version 0.24.0 to 0.47.0 in requirements.txt
   - Version 0.47.0 is the first version to support extended thinking with Claude 3.7 models

2. **Fixed Code Implementation**
   - Modified embeddings_impact_analyzer.py to use `messages.create()` instead of `messages.stream()` with thinking parameter
   - Extended thinking is not compatible with streaming API
   - Improved logging to reflect the use of extended thinking

3. **Added Test File**
   - Created tests/anthropic_test.py to verify Claude 3.7 with extended thinking
   - This can be used to test the implementation after installing the updated SDK

## Steps to Apply Fix

1. Install the updated Anthropic SDK:
   ```
   pip install anthropic==0.47.0
   ```

2. Verify the implementation works:
   ```
   python -m tests.anthropic_test
   ```

3. Run the application:
   ```
   python main.py
   ```

## Implementation Details

The fix changes how extended thinking is used with Claude 3.7. Instead of trying to use the streaming API with the thinking parameter (which caused the error), we now use the standard messages.create() method with the thinking parameter.

The key code change:
```python
# Create thinking parameter for non-streaming API
thinking_params = params.copy()
thinking_params["thinking"] = {
    "type": "enabled",
    "budget_tokens": 16000
}

# Use standard create method (non-streaming) for Claude 3.7 with extended thinking
response = await self.anthropic_client.messages.create(**thinking_params)
```

We keep the budget_tokens (16000) lower than the max_tokens (64000) to ensure compatibility.