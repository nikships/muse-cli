import importlib.util
import io
import json
import os
import threading
import unittest
from unittest.mock import MagicMock, patch

from curl_cffi.requests.websockets import WebSocketTimeout

from muse_cli import gateway
from muse_cli.gateway import (ROUTES, SERVICE_IDS, Gateway, GatewayError, NoiseTransportFrame,
                              ServiceFrame, ServiceResponse)


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


def frame_payload(stream_id, kind, body=b"", end=False, status=200, headers=()):
    sf = ServiceFrame(stream_id=stream_id)
    if kind == "response":
        sf.response.status = status
        sf.response.body = body
        sf.response.end_body = end
        for k, v in headers:
            h = sf.response.headers.add()
            h.key, h.value = k, v
    else:
        sf.body_chunk.data = body
        sf.body_chunk.end_body = end
    return transport(ServiceResponse(payload=sf.SerializeToString()).SerializeToString())


def sending_gateway(frames=()):
    gw = make_gateway(list(frames))
    gw.stream = 7
    gw.sent = []
    gw._send_envelope = lambda service, data: gw.sent.append((service, ServiceFrame.FromString(data)))
    return gw


class OpenRequestTest(unittest.TestCase):
    def test_list_query_values_become_repeated_keys(self):
        gw = sending_gateway()
        gw._open("voice.catalog", query={"source": "library", "gender": ["F", "M"], "query": None})
        self.assertEqual(gw.sent[0][1].request.path,
                         "/api/voice/catalog?source=library&gender=F&gender=M")

    def test_empty_body_routes_drop_the_body(self):
        gw = sending_gateway()
        gw._open("dyi.export", body={"x": 1})
        req = gw.sent[0][1].request
        self.assertEqual(req.body, b"")
        self.assertNotIn("content-type", [h.key for h in req.headers])

    def test_new_services_use_their_ids(self):
        gw = sending_gateway()
        gw._open("rv_migration.enable_export")
        gw._open("ssh.operator.enable")
        self.assertEqual([s for s, _ in gw.sent], [5, 4])


class StreamingRequestTest(unittest.TestCase):
    def test_request_to_streams_chunks_and_returns_headers(self):
        gw = sending_gateway([
            frame_payload(3, "body_chunk", b"other stream", end=True),
            frame_payload(7, "response", b"PK", headers=[("Content-Type", "application/zip")]),
            frame_payload(7, "body_chunk", b"ab"),
            frame_payload(7, "body_chunk", b"cd", end=True),
        ])
        fh, seen = io.BytesIO(), []
        headers = gw.request_to(fh, "dyi.export", on_progress=seen.append)
        self.assertEqual(fh.getvalue(), b"PKabcd")
        self.assertEqual(headers["content-type"], "application/zip")
        self.assertEqual(seen, [2, 4, 6])

    def test_error_status_raises_without_writing(self):
        gw = sending_gateway([
            frame_payload(7, "response", b'{"error":"nope"}', end=True, status=403)])
        fh = io.BytesIO()
        with self.assertRaises(GatewayError) as ctx:
            gw.request_to(fh, "dyi.export")
        self.assertEqual(ctx.exception.status, 403)
        self.assertIn("nope", str(ctx.exception))
        self.assertEqual(fh.getvalue(), b"")

    def test_request_joins_body_chunks(self):
        gw = sending_gateway([frame_payload(7, "response", b'{"a":'),
                              frame_payload(7, "body_chunk", b"1}", end=True)])
        self.assertEqual(gw.call_json("tasks.list"), {"a": 1})


class ResponseDeadlineTest(unittest.TestCase):
    def stalling_gateway(self, frames, arrival=4):
        gw = sending_gateway()
        clock = [0]
        pending = list(frames)

        def recv(timeout=None):
            if pending:
                clock[0] += arrival
                return pending.pop(0), 0
            if timeout is None:
                raise AssertionError("socket wait has no time limit")
            clock[0] += timeout
            raise WebSocketTimeout("no data")
        gw.ws.recv.side_effect = recv
        return gw, clock

    def test_silent_socket_times_out_within_the_request_timeout(self):
        gw, clock = self.stalling_gateway([])
        with patch.object(gateway.time, "monotonic", lambda: clock[0]), \
                self.assertRaises(TimeoutError):
            gw.request("tasks.list", timeout=5)
        self.assertLessEqual(clock[0], 5)

    def test_reply_that_stalls_between_chunks_times_out_within_the_request_timeout(self):
        payload = response_payload(b"x" * 5000)
        gw, clock = self.stalling_gateway(
            [transport(payload[:2500], chunk_id=-5, index=0, total=2)])
        with patch.object(gateway.time, "monotonic", lambda: clock[0]), \
                self.assertRaises(TimeoutError):
            gw.request("tasks.list", timeout=5)
        self.assertLessEqual(clock[0], 5)


class RouteTableTest(unittest.TestCase):
    def test_routes_are_unique_and_use_known_services(self):
        with open(os.path.join(os.path.dirname(gateway.__file__), "routes.json")) as fh:
            routes = json.load(fh)
        names = [r["method"] for r in routes]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(routes), len(ROUTES))
        for r in routes:
            self.assertIn(r.get("service", "daemon"), SERVICE_IDS, r["method"])
            self.assertIn(r["http"], ("GET", "POST", "PUT", "PATCH", "DELETE"), r["method"])
        for name in ("chat.history", "tasks.run", "email.threads.list", "dyi.export", "peers.status"):
            self.assertIn(name, ROUTES)

    def test_service_enum_matches_service_ids(self):
        enum = gateway._pool.FindEnumTypeByName("hatch.noise.ServiceType")
        self.assertEqual({v.name: v.number for v in enum.values},
                         {f"SERVICE_{k.upper()}": v for k, v in SERVICE_IDS.items()})


class ExtractRoutesTest(unittest.TestCase):
    def load(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "extract_routes.py")
        spec = importlib.util.spec_from_file_location("extract_routes", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_parses_route_literals(self):
        mod = self.load()
        src = ('x=[{method:"a.b",httpMethod:"GET",path:"/a/{id}",noiseOnly:!0,requestTimeoutMs:12e4,'
               'maxResponseBytes:1/0},{method:"c",httpMethod:"POST",path:"/c",service:"authd",'
               'aliases:["/old"],streaming:!1,maxResponseBytes:0x2400000}]')
        routes = [mod.parse_route(mod.literal(src, i)) for i in (src.index("{method"), src.index('{method:"c"'))]
        self.assertEqual(routes[0], {"method": "a.b", "http": "GET", "path": "/a/{id}",
                                     "noiseOnly": True, "requestTimeoutMs": 120000})
        self.assertEqual(routes[1], {"method": "c", "http": "POST", "path": "/c", "service": "authd",
                                     "aliases": ["/old"], "streaming": False,
                                     "maxResponseBytes": 0x2400000})


if __name__ == "__main__":
    unittest.main()
