"""Üretim iptali birim testleri."""

import unittest

from llm.cancel import CancelWatch, GenerationCancelled


class TestCancelWatch(unittest.TestCase):
    def test_check_raises_when_tripped(self):
        watch = CancelWatch()
        watch.event.set()
        with self.assertRaises(GenerationCancelled):
            watch.check()

    def test_check_passes_when_idle(self):
        watch = CancelWatch()
        watch.check()

    def test_bind_closer_called_if_already_set(self):
        watch = CancelWatch()
        watch.event.set()
        called = []
        watch.bind_closer(lambda: called.append(1))
        self.assertEqual(called, [1])


if __name__ == "__main__":
    unittest.main()
