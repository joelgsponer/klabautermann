"""
Pytest configuration and shared fixtures for Klabautermann tests.

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""

import asyncio
from collections.abc import Generator
from typing import Any

import pytest


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_neo4j_driver() -> Any:
    """Mock Neo4j driver for unit tests."""
    # TODO: Implement mock driver in T010
    pass


@pytest.fixture
def mock_anthropic_client() -> Any:
    """Mock Anthropic client for unit tests."""
    # TODO: Implement mock client in T017
    pass


@pytest.fixture
def sample_thread_context() -> dict[str, Any]:
    """Sample thread context for testing."""
    return {
        "thread_uuid": "test-thread-uuid",
        "channel_type": "cli",
        "messages": [
            {"role": "user", "content": "Hello, I met Sarah from Acme Corp today."},
            {"role": "assistant", "content": "Nice to meet Sarah! What does she do at Acme?"},
        ],
    }
