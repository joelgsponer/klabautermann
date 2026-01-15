"""
Unit tests for the retry utility.

Tests exponential backoff, jitter, exception filtering, and convenience decorators.
"""
# ruff: noqa: SIM117

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from klabautermann.utils.retry import (
    retry_on_connection,
    retry_on_timeout,
    with_retry,
)


class TestWithRetry:
    """Tests for the with_retry decorator."""

    @pytest.mark.asyncio
    async def test_successful_call_no_retry(self) -> None:
        """Function succeeds on first call - no retries needed."""
        call_count = 0

        @with_retry(max_retries=3)
        async def always_succeeds() -> str:
            nonlocal call_count
            call_count += 1
            return "success"

        result = await always_succeeds()

        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_matching_exception(self) -> None:
        """Function retries when matching exception is raised."""
        call_count = 0

        @with_retry(max_retries=3, retry_on=(ConnectionError,), base_delay=0.01)
        async def fails_twice() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Connection failed")
            return "success"

        result = await fails_twice()

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self) -> None:
        """Function raises after exhausting retries."""
        call_count = 0

        @with_retry(max_retries=2, retry_on=(TimeoutError,), base_delay=0.01)
        async def always_fails() -> str:
            nonlocal call_count
            call_count += 1
            raise TimeoutError("Always times out")

        with pytest.raises(TimeoutError):
            await always_fails()

        # Initial attempt + 2 retries = 3 total calls
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_excluded_exception(self) -> None:
        """Function raises immediately on no_retry_on exceptions."""
        call_count = 0

        @with_retry(
            max_retries=3,
            retry_on=(ConnectionError, ValueError),
            no_retry_on=(ValueError,),
            base_delay=0.01,
        )
        async def raises_value_error() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("Invalid input")

        with pytest.raises(ValueError):
            await raises_value_error()

        # Should fail immediately without retries
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_no_retry_on_unexpected_exception(self) -> None:
        """Function raises immediately on unexpected exceptions."""
        call_count = 0

        @with_retry(max_retries=3, retry_on=(TimeoutError,), base_delay=0.01)
        async def raises_key_error() -> str:
            nonlocal call_count
            call_count += 1
            raise KeyError("Missing key")

        with pytest.raises(KeyError):
            await raises_key_error()

        # Should fail immediately - KeyError not in retry_on
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_exponential_backoff_delay(self) -> None:
        """Verify delay increases exponentially between retries."""
        delays: list[float] = []
        call_count = 0

        @with_retry(
            max_retries=3,
            retry_on=(ConnectionError,),
            base_delay=0.1,
            multiplier=2.0,
            jitter=0.0,  # Disable jitter for predictable delays
        )
        async def fails_always() -> str:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Always fails")

        # Patch asyncio.sleep to capture delays
        original_sleep = asyncio.sleep

        async def mock_sleep(delay: float) -> None:
            delays.append(delay)
            await original_sleep(0.001)  # Minimal actual delay

        with patch("klabautermann.utils.retry.asyncio.sleep", mock_sleep):
            with pytest.raises(ConnectionError):
                await fails_always()

        # Should have 3 delays (after attempts 1, 2, 3, before failing on 4)
        assert len(delays) == 3
        # Delays should follow exponential pattern: 0.1, 0.2, 0.4
        assert delays[0] == pytest.approx(0.1, rel=0.01)
        assert delays[1] == pytest.approx(0.2, rel=0.01)
        assert delays[2] == pytest.approx(0.4, rel=0.01)

    @pytest.mark.asyncio
    async def test_max_delay_cap(self) -> None:
        """Verify delay is capped at max_delay."""
        delays: list[float] = []

        @with_retry(
            max_retries=5,
            retry_on=(ConnectionError,),
            base_delay=1.0,
            multiplier=10.0,
            max_delay=5.0,
            jitter=0.0,
        )
        async def fails_always() -> str:
            raise ConnectionError("Always fails")

        original_sleep = asyncio.sleep

        async def mock_sleep(delay: float) -> None:
            delays.append(delay)
            await original_sleep(0.001)

        with patch("klabautermann.utils.retry.asyncio.sleep", mock_sleep):
            with pytest.raises(ConnectionError):
                await fails_always()

        # All delays should be capped at max_delay=5.0
        for delay in delays[1:]:  # First delay is 1.0, rest should be capped
            assert delay <= 5.0

    @pytest.mark.asyncio
    async def test_jitter_randomizes_delay(self) -> None:
        """Verify jitter adds randomness to delays."""
        delays_run1: list[float] = []
        delays_run2: list[float] = []

        @with_retry(
            max_retries=3,
            retry_on=(ConnectionError,),
            base_delay=1.0,
            multiplier=1.0,  # Keep same base for easier comparison
            jitter=0.25,  # 25% jitter
        )
        async def fails_always() -> str:
            raise ConnectionError("Always fails")

        async def mock_sleep(capture_list: list[float]) -> AsyncMock:
            async def _sleep(delay: float) -> None:
                capture_list.append(delay)

            return _sleep

        # Run twice and capture delays
        with patch("klabautermann.utils.retry.asyncio.sleep", await mock_sleep(delays_run1)):
            with pytest.raises(ConnectionError):
                await fails_always()

        with patch("klabautermann.utils.retry.asyncio.sleep", await mock_sleep(delays_run2)):
            with pytest.raises(ConnectionError):
                await fails_always()

        # Delays should be within jitter range of base_delay
        for delay in delays_run1 + delays_run2:
            assert 0.75 <= delay <= 1.25  # base_delay * (1 +/- jitter)

    @pytest.mark.asyncio
    async def test_preserves_function_metadata(self) -> None:
        """Verify decorator preserves original function metadata."""

        @with_retry(max_retries=3)
        async def documented_function() -> str:
            """This function has documentation."""
            return "result"

        assert documented_function.__name__ == "documented_function"
        assert "documentation" in (documented_function.__doc__ or "")


class TestRetryOnTimeout:
    """Tests for the retry_on_timeout convenience decorator."""

    @pytest.mark.asyncio
    async def test_retries_on_timeout_error(self) -> None:
        """Retry on TimeoutError."""
        call_count = 0

        @retry_on_timeout(max_retries=2)
        async def times_out_once() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("Timed out")
            return "success"

        with patch("klabautermann.utils.retry.asyncio.sleep", AsyncMock()):
            result = await times_out_once()

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_asyncio_timeout_error(self) -> None:
        """Retry on asyncio.TimeoutError."""
        call_count = 0

        @retry_on_timeout(max_retries=2)
        async def times_out_once() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("Async timeout")
            return "success"

        with patch("klabautermann.utils.retry.asyncio.sleep", AsyncMock()):
            result = await times_out_once()

        assert result == "success"
        assert call_count == 2


class TestRetryOnConnection:
    """Tests for the retry_on_connection convenience decorator."""

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self) -> None:
        """Retry on ConnectionError."""
        call_count = 0

        @retry_on_connection(max_retries=2)
        async def connection_fails_once() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Connection refused")
            return "success"

        with patch("klabautermann.utils.retry.asyncio.sleep", AsyncMock()):
            result = await connection_fails_once()

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_os_error(self) -> None:
        """Retry on OSError (network issues)."""
        call_count = 0

        @retry_on_connection(max_retries=2)
        async def os_error_once() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Network unreachable")
            return "success"

        with patch("klabautermann.utils.retry.asyncio.sleep", AsyncMock()):
            result = await os_error_once()

        assert result == "success"
        assert call_count == 2
