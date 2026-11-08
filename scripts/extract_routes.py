"""Regenerate routes.json and the protobuf descriptors from the muse.ai web app.

    uv run python scripts/extract_routes.py            # crawl https://muse.ai/
    uv run python scripts/extract_routes.py --dir DIR  # use already-downloaded chunks

The web client ships its gateway route table as JS object literals
({method:"chat.history",httpMethod:"GET",path:"/chat/history",...}) and the
Noise envelope descriptors as base64 FileDescriptorProto blobs. Logged out,
muse.ai serves only the marketing page, so the crawl loads the app shell with
the saved muse-cli login (cookies are sent to that one HTML page only; the
static chunks are public).
"""
import argparse
import base64
import concurrent.futures
import json
import os
import re
import sys

from curl_cffi import requests as rq
from google.protobuf import descriptor_pb2

from muse_cli.gateway import _hatch_headers, load_cookies

ORIGIN = "https://muse.ai"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "muse_cli")
DESCRIPTORS = {"noise_transport.proto": "desc0.bin", "noise_envelope.proto": "desc1.bin"}
CHUNK_RE = re.compile(r"static/chunks/([A-Za-z0-9_\-~.]+\.js)")


def crawl(cookies_file):
    """Download every JS chunk reachable from the logged-in app shell."""
    headers = dict(_hatch_headers(load_cookies(cookies_file)), Accept="text/html")
    html = rq.get(ORIGIN + "/", headers=headers, impersonate="chrome", timeout=30).text
    todo, seen, chunks = set(CHUNK_RE.findall(html)), set(), {}

    def get(name):
        r = rq.get(f"{ORIGIN}/_next/static/chunks/{name}", impersonate="chrome", timeout=30)
        return name, r.text if r.status_code == 200 else None

    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        while todo:
            seen |= todo
            for name, text in pool.map(get, sorted(todo)):
                if text is not None:
                    chunks[name] = text
            todo = {n for t in chunks.values() for n in CHUNK_RE.findall(t)} - seen
    return chunks


def literal(src, start):
    """Return the balanced {...} JS object literal starting at src[start]."""
    depth, i, in_str = 0, start, False
    while True:
        c = src[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1


VALUE_RE = re.compile(r'(\w+):("(?:[^"\\]|\\.)*"|!0|!1|\[[^\]]*\]|1/0|[\w.+-]+)')


def parse_route(obj):
    fields = {}
    for key, raw in VALUE_RE.findall(obj):
        if raw in ("!0", "!1"):
            fields[key] = raw == "!0"
        elif raw.startswith(("\"", "[")):
            fields[key] = json.loads(raw)
        elif raw == "1/0":
            continue  # Infinity: no limit
        else:
            fields[key] = int(raw, 16) if raw.lower().startswith("0x") else int(float(raw))
    route = {"method": fields.pop("method"), "http": fields.pop("httpMethod"), "path": fields.pop("path")}
    route.update(fields)
    return route


def extract(chunks):
    routes = []
    for text in chunks.values():
        if '{method:"chat.history",httpMethod:' in text:
            routes = [parse_route(literal(text, m.start()))
                      for m in re.finditer(r'\{method:"[^"]+",httpMethod:', text)]
            break
    descs = {}
    for text in chunks.values():
        for blob in re.findall(r'"(Ch[A-Za-z0-9+/=]{40,})"', text):
            try:
                raw = base64.b64decode(blob + "=" * (-len(blob) % 4))
                fd = descriptor_pb2.FileDescriptorProto.FromString(raw)
            except Exception:  # noqa: BLE001 - most matches are not descriptors
                continue
            if fd.name in DESCRIPTORS:
                descs[DESCRIPTORS[fd.name]] = raw
    return routes, descs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", help="directory of downloaded *.js chunks (default: crawl muse.ai)")
    ap.add_argument("--cookies", default=os.path.expanduser("~/.config/muse-cli/cookies.txt"),
                    help="muse-cli cookie file used to load the app shell")
    ap.add_argument("--out", default=OUT, help="where to write routes.json and desc*.bin")
    args = ap.parse_args()
    if args.dir:
        chunks = {}
        for name in os.listdir(args.dir):
            if name.endswith(".js"):
                with open(os.path.join(args.dir, name), encoding="utf-8", errors="replace") as fh:
                    chunks[name] = fh.read()
    else:
        chunks = crawl(args.cookies)
    routes, descs = extract(chunks)
    if not routes or len(descs) != len(DESCRIPTORS):
        sys.exit(f"route table or descriptors not found in {len(chunks)} chunks; "
                 "is the login current (muse-cli status)? Otherwise the bundle changed shape")
    names = [r["method"] for r in routes]
    if len(set(names)) != len(names):
        sys.exit("duplicate method names in the route table")
    with open(os.path.join(args.out, "routes.json"), "w") as fh:
        json.dump(routes, fh, indent=1)
        fh.write("\n")
    for name, raw in descs.items():
        with open(os.path.join(args.out, name), "wb") as fh:
            fh.write(raw)
    print(f"{len(routes)} methods from {len(chunks)} chunks -> {args.out}")


if __name__ == "__main__":
    main()
