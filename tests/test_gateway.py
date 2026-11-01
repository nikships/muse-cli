import threading
import unittest
from unittest.mock import MagicMock

from muse_cli.gateway import Gateway, NoiseTransportFrame, ServiceFrame, ServiceResponse


def make_gateway(frames):
    """A Gateway whose socket yields `frames` (already-serialized transport frames)."""
    gw = Gateway.__new__(Gateway)
    gw._recv_lock = threading.Lock()
    gw._chunks = {}
    gw.ws = MagicMock()
    gw.ws.recv.side_effect = [(f, 0) for f in frames]
    gw.noise = MagicMock()
    gw.noise.decrypt.side_effect = lambda data: data
    return gw


def response_payload(body, stream_id=7):
    sf = ServiceFrame(stream_id=stream_id)
    sf.response.status = 200
    sf.response.body = body
    sf.response.end_body = True
    return ServiceResponse(payload=sf.SerializeToString()).SerializeToString()


def transport(payload, chunk_id=1, index=0, total=1):
    return NoiseTransportFrame(chunk_id=chunk_id, chunk_index=index, total_chunks=total,
                               payload=payload).SerializeToString()


class ReadFrameTest(unittest.TestCase):
    def test_single_frame(self):
        gw = make_gateway([transport(response_payload(b"hi"))])
        sf = gw._read_frame()
        self.assertEqual(sf.stream_id, 7)
        self.assertEqual(sf.response.body, b"hi")

    def test_frame_without_total_chunks_counts_as_one(self):
        raw = NoiseTransportFrame(chunk_id=1, payload=response_payload(b"hi")).SerializeToString()
        self.assertEqual(make_gateway([raw])._read_frame().response.body, b"hi")

    def test_reassembles_chunks(self):
        payload = response_payload(b"x" * 5000)
        third = len(payload) // 3
        parts = [payload[:third], payload[third:2 * third], payload[2 * third:]]
        gw = make_gateway([transport(p, chunk_id=-5, index=i, total=3) for i, p in enumerate(parts)])
        sf = gw._read_frame()
        self.assertEqual(sf.response.body, b"x" * 5000)
        self.assertEqual(gw.ws.recv.call_count, 3)
        self.assertEqual(gw._chunks, {})

    def test_reassembles_out_of_order_and_interleaved(self):
        a, b = response_payload(b"a" * 100, 1), response_payload(b"b" * 100, 2)
        frames = [
            transport(a[:40], chunk_id=10, index=0, total=2),
            transport(b[40:], chunk_id=11, index=1, total=2),
            transport(b[:40], chunk_id=11, index=0, total=2),
            transport(a[40:], chunk_id=10, index=1, total=2),
        ]
        gw = make_gateway(frames)
        first, second = gw._read_frame(), gw._read_frame()
        self.assertEqual((first.stream_id, first.response.body), (2, b"b" * 100))
        self.assertEqual((second.stream_id, second.response.body), (1, b"a" * 100))
        self.assertEqual(gw._chunks, {})

    def test_single_frames_between_chunks_are_not_swallowed(self):
        payload = response_payload(b"y" * 200, 1)
        frames = [
            transport(payload[:50], chunk_id=3, index=0, total=2),
            transport(response_payload(b"small", 2), chunk_id=4),
            transport(payload[50:], chunk_id=3, index=1, total=2),
        ]
        gw = make_gateway(frames)
        self.assertEqual(gw._read_frame().response.body, b"small")
        self.assertEqual(gw._read_frame().response.body, b"y" * 200)


if __name__ == "__main__":
    unittest.main()
