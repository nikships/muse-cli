import unittest

from muse_cli.cli import event_resources
from muse_cli.gateway import media_path

P = "sandbox://workspace/imagine_media/cat 1.mp4"
URL = "https://abc.metaaivm.com/media/raw/workspace/imagine_media/cat%201.mp4"


class MediaPathTest(unittest.TestCase):
    def test_forms(self):
        want = "/media/raw/workspace/imagine_media/cat%201.mp4"
        self.assertEqual(media_path(P), want)
        self.assertEqual(media_path(URL), want)
        self.assertEqual(media_path("/media/raw/workspace/imagine_media/cat 1.mp4"), want)
        self.assertEqual(media_path({"path": P, "variants": {"original": URL}}), want)

    def test_rejects_traversal(self):
        with self.assertRaises(ValueError):
            media_path("sandbox://workspace/../etc/passwd")


class EventResourcesTest(unittest.TestCase):
    def test_videos_and_links_dedupe(self):
        P = "sandbox://workspace/imagine_media/cat-1.mp4"
        ev = {"seq": 1, "payload": {
            "fallback_text": f"![v]({P})",
            "data": {"videos": [{"path": P, "mime": "video/mp4", "byte_len": 5}],
                     "images": [{"path": "sandbox://workspace/x.png", "missing": True}]}}}
        res = event_resources(ev)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["kind"], "video")
        self.assertEqual(res[0]["byte_len"], 5)

    def test_no_files(self):
        self.assertEqual(event_resources({"payload": {"display_text": "hi"}}), [])


if __name__ == "__main__":
    unittest.main()
