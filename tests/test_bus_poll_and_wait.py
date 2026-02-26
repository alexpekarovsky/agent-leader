"""Tests for EventBus.poll_events and EventBus.wait_for_event_index.

These are the two untested synchronization primitives in the bus module.
Tests use short timeouts to keep execution bounded.
"""

from __future__ import annotations

import json
import tempfile
import time
import threading
import unittest
from pathlib import Path

from orchestrator.bus import EventBus


class PollEventsImmediateTests(unittest.TestCase):
    """Tests for poll_events with immediate returns."""

    def test_returns_events_when_exist_no_timeout(self) -> None:
        """poll_events with timeout<=0 returns existing events immediately."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))
            bus.emit("test.event", {"key": "value"}, source="test")

            events = list(bus.poll_events(timeout_ms=0))

            self.assertGreaterEqual(len(events), 1)
            self.assertEqual("test.event", events[0]["type"])

    def test_returns_empty_when_no_events_no_timeout(self) -> None:
        """poll_events with timeout<=0 returns empty list when no events."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))

            events = list(bus.poll_events(timeout_ms=0))

            self.assertEqual([], events)

    def test_negative_timeout_returns_immediately(self) -> None:
        """Negative timeout should behave like timeout=0."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))

            start = time.time()
            events = list(bus.poll_events(timeout_ms=-100))
            elapsed = time.time() - start

            self.assertEqual([], events)
            self.assertLess(elapsed, 1.0)

    def test_returns_events_immediately_with_timeout(self) -> None:
        """When events exist, poll_events returns immediately even with timeout."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))
            bus.emit("existing.event", {"n": 1}, source="test")

            start = time.time()
            events = list(bus.poll_events(timeout_ms=5000))
            elapsed = time.time() - start

            self.assertGreaterEqual(len(events), 1)
            # Should return well before the 5-second timeout
            self.assertLess(elapsed, 2.0)


class PollEventsTimeoutTests(unittest.TestCase):
    """Tests for poll_events timeout behavior."""

    def test_waits_then_returns_empty_on_timeout(self) -> None:
        """poll_events with timeout should wait then return empty."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))

            start = time.time()
            events = list(bus.poll_events(timeout_ms=200))
            elapsed = time.time() - start

            self.assertEqual([], events)
            # Should have waited at least ~200ms
            self.assertGreaterEqual(elapsed, 0.15)

    def test_returns_events_added_during_poll(self) -> None:
        """Events added while polling should be returned."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))

            def add_event_later():
                time.sleep(0.1)
                bus.emit("delayed.event", {"delayed": True}, source="test")

            thread = threading.Thread(target=add_event_later)
            thread.start()

            events = list(bus.poll_events(timeout_ms=3000))
            thread.join()

            self.assertGreaterEqual(len(events), 1)
            delayed = [e for e in events if e.get("type") == "delayed.event"]
            self.assertEqual(1, len(delayed))

    def test_returns_all_events_not_just_new(self) -> None:
        """poll_events returns all events, not just ones added during polling."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))
            bus.emit("before.poll", {"n": 1}, source="test")
            bus.emit("before.poll", {"n": 2}, source="test")

            events = list(bus.poll_events(timeout_ms=100))

            self.assertEqual(2, len(events))


class PollEventsReturnTypeTests(unittest.TestCase):
    """Tests for poll_events return type."""

    def test_returns_iterable(self) -> None:
        """poll_events should return an iterable."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))

            result = bus.poll_events(timeout_ms=0)

            self.assertIsInstance(list(result), list)

    def test_events_are_dicts(self) -> None:
        """Each event should be a dict."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))
            bus.emit("test.type", {"k": "v"}, source="test")

            events = list(bus.poll_events(timeout_ms=0))

            for event in events:
                self.assertIsInstance(event, dict)


class WaitForEventIndexBasicTests(unittest.TestCase):
    """Tests for wait_for_event_index basic behavior."""

    def test_returns_immediately_when_no_timeout(self) -> None:
        """timeout_ms <= 0 should return immediately."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))

            start = time.time()
            bus.wait_for_event_index(start=10, timeout_ms=0)
            elapsed = time.time() - start

            self.assertLess(elapsed, 0.5)

    def test_returns_immediately_with_negative_timeout(self) -> None:
        """Negative timeout should return immediately."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))

            start = time.time()
            bus.wait_for_event_index(start=5, timeout_ms=-100)
            elapsed = time.time() - start

            self.assertLess(elapsed, 0.5)

    def test_returns_immediately_when_index_already_reached(self) -> None:
        """When enough events already exist, should return immediately."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))
            for i in range(5):
                bus.emit(f"event.{i}", {"n": i}, source="test")

            start = time.time()
            bus.wait_for_event_index(start=3, timeout_ms=5000)
            elapsed = time.time() - start

            self.assertLess(elapsed, 1.0)

    def test_waits_for_events_to_reach_index(self) -> None:
        """Should wait until enough events are written."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))
            bus.emit("initial", {}, source="test")

            def add_events_later():
                time.sleep(0.15)
                for i in range(5):
                    bus.emit(f"later.{i}", {"n": i}, source="test")

            thread = threading.Thread(target=add_events_later)
            thread.start()

            start = time.time()
            bus.wait_for_event_index(start=4, timeout_ms=3000)
            elapsed = time.time() - start

            thread.join()

            # Should have returned after events were added (~0.15s) not at timeout (~3s)
            self.assertLess(elapsed, 2.0)
            self.assertGreater(elapsed, 0.1)


class WaitForEventIndexTimeoutTests(unittest.TestCase):
    """Tests for wait_for_event_index timeout behavior."""

    def test_times_out_when_index_not_reached(self) -> None:
        """Should return after timeout even if index not reached."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))

            start = time.time()
            bus.wait_for_event_index(start=100, timeout_ms=200)
            elapsed = time.time() - start

            # Should have waited approximately 200ms
            self.assertGreaterEqual(elapsed, 0.15)
            self.assertLess(elapsed, 2.0)

    def test_returns_none(self) -> None:
        """wait_for_event_index should return None."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))

            result = bus.wait_for_event_index(start=0, timeout_ms=0)

            self.assertIsNone(result)

    def test_start_zero_with_any_events(self) -> None:
        """start=0 should return immediately if any event exists."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))
            bus.emit("one.event", {}, source="test")

            start = time.time()
            bus.wait_for_event_index(start=0, timeout_ms=5000)
            elapsed = time.time() - start

            self.assertLess(elapsed, 1.0)


if __name__ == "__main__":
    unittest.main()
