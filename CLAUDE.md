# CLAUDE.md - Coding Guide

## Build Commands
- **Run Python Backend**: `python main.py`
- **Run Frontend Dev Server**: `cd frontend && npm run dev`
- **Build Frontend**: `cd frontend && npm run build`
- **Watch Frontend**: `cd frontend && npm run watch`
- **Run Diagnostics**: `python -m tests.diag`
- **Run Single Test**: `python -m tests.openai_test`

## Code Style Guidelines

### Python
- **Imports**: Standard library → third-party → local modules
- **Type Annotations**: Use type hints (`from typing import List, Optional, Dict`)
- **Classes**: Use dataclasses for data models with type annotations
- **Naming**: 
  - snake_case for functions/variables
  - PascalCase for classes
  - UPPER_CASE for constants
- **Error Handling**: Use try/except with specific exceptions
- **Logging**: Use the standard logging module (configured in logging_config.py)

### JavaScript/React
- **Component Structure**: Functional components with hooks
- **Styling**: Use TailwindCSS with class-variance-authority
- **UI Components**: Leverage Radix UI primitives in the UI folder