import unittest
from unittest.mock import patch

from scalperlab.research import (
    ResearchError,
    _normal_result,
    _validate_public_https_url,
    parse_feed,
)


class ResearchTests(unittest.TestCase):
    def test_local_urls_are_rejected(self):
        with self.assertRaises(ResearchError):
            _validate_public_https_url("https://127.0.0.1/admin")
        with self.assertRaises(ResearchError):
            _validate_public_https_url("http://example.com/article")

    @patch("scalperlab.research.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))])
    def test_rss_relative_links_are_resolved_to_feed_host(self, _resolver):
        xml = b"""<?xml version='1.0'?><rss><channel><item><title>Breakout MQL5</title><link>/articles/42</link><description>Evidence excerpt</description><pubDate>Tue, 22 Sep 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
        items = parse_feed(xml, "Research blog", "https://example.com/feed.xml")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://example.com/articles/42")
        self.assertEqual(items[0]["source"], "Research blog")
        self.assertEqual(items[0]["published_at"], "Tue, 22 Sep 2026 10:00:00 GMT")

    @patch("scalperlab.research.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))])
    def test_provider_result_private_host_is_rejected(self, _resolver):
        with self.assertRaises(ResearchError):
            _normal_result("Internal", "https://private.example/admin", "provider")


if __name__ == "__main__":
    unittest.main()
