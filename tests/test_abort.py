"""İptalde soket kapatma birim testleri."""

import socket
import unittest
from unittest import mock

from llm.abort import abort_provider_task, abort_stream, _shutdown_socket


class FakeSocket:
    def __init__(self):
        self.shutdown_how = None
        self.closed = False

    def shutdown(self, how):
        self.shutdown_how = how

    def close(self):
        self.closed = True


class NestedStream:
    def __init__(self, sock):
        self._stream = type("Inner", (), {"_sock": sock})()

    def close(self):
        self.closed = True


class TestAbortStream(unittest.TestCase):
    def test_shutdowns_nested_socket(self):
        sock = FakeSocket()
        stream = NestedStream(sock)
        abort_stream(stream)
        self.assertEqual(sock.shutdown_how, socket.SHUT_RDWR)
        self.assertTrue(sock.closed)
        self.assertTrue(getattr(stream, "closed", False))

    def test_httpx_style_extensions(self):
        sock = FakeSocket()
        net = type("Net", (), {})()
        net.get_extra_info = lambda key: sock if key == "socket" else None
        resp = type("Resp", (), {})()
        resp.extensions = {"network_stream": net}
        resp.close = lambda: setattr(resp, "closed", True)
        abort_stream(resp)
        self.assertEqual(sock.shutdown_how, socket.SHUT_RDWR)
        self.assertTrue(sock.closed)

    def test_provider_abort_does_not_raise(self):
        with mock.patch("llm.abort.urllib.request.urlopen",
                        side_effect=OSError("down")):
            abort_provider_task("http://127.0.0.1:8080/v1", None)


class TestShutdownWalk(unittest.TestCase):
    def test_ignores_none(self):
        _shutdown_socket(None)


if __name__ == "__main__":
    unittest.main()
