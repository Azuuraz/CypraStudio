import os
import unittest
from unittest.mock import patch


class SecurityContractTests(unittest.TestCase):
    def test_loopback_host_header_accepts_only_local_names(self):
        from engine.security import host_header_is_loopback

        self.assertTrue(host_header_is_loopback("127.0.0.1:8765"))
        self.assertTrue(host_header_is_loopback("localhost:8765"))
        self.assertTrue(host_header_is_loopback("[::1]:8765"))
        self.assertFalse(host_header_is_loopback("example.com:8765"))
        self.assertFalse(host_header_is_loopback("127.0.0.1.evil.test:8765"))

    def test_same_origin_rejects_cross_site_browser_origin(self):
        from engine.security import origin_matches_request

        self.assertTrue(origin_matches_request("http://127.0.0.1:8765", "http://127.0.0.1:8765"))
        self.assertTrue(origin_matches_request("http://localhost:8765", "http://localhost:8765"))
        self.assertFalse(origin_matches_request("https://evil.example", "http://127.0.0.1:8765"))
        self.assertFalse(origin_matches_request("null", "http://127.0.0.1:8765"))

    def test_image_signature_must_match_declared_type(self):
        from engine.security import valid_image_signature

        png = b"\x89PNG\r\n\x1a\n" + b"x" * 40
        jpeg = b"\xff\xd8\xff\xe0" + b"x" * 40
        webp = b"RIFF" + (40).to_bytes(4, "little") + b"WEBP" + b"x" * 40
        self.assertTrue(valid_image_signature(png, "image/png"))
        self.assertTrue(valid_image_signature(jpeg, "image/jpeg"))
        self.assertTrue(valid_image_signature(webp, "image/webp"))
        self.assertFalse(valid_image_signature(png, "image/jpeg"))
        self.assertFalse(valid_image_signature(b"<script>alert(1)</script>", "image/png"))

    def test_ollama_root_refuses_remote_environment_endpoint(self):
        from engine import llm

        with patch.dict(os.environ, {"OLLAMA_HOST": "https://evil.example:443"}, clear=False):
            with self.assertRaises(ValueError):
                llm.ollama_root()

    def test_ollama_root_allows_loopback_custom_port(self):
        from engine import llm

        with patch.dict(os.environ, {"OLLAMA_HOST": "127.0.0.1:11435"}, clear=False):
            self.assertEqual(llm.ollama_root(), "http://127.0.0.1:11435")

    def test_model_store_cannot_be_redirected_by_environment(self):
        from engine import llm

        expected = str((llm.ROOT / "OllamaModels").resolve())
        with patch.dict(os.environ, {"OLLAMA_MODELS": str(llm.ROOT / ".." / "HostModels")}, clear=False):
            self.assertEqual(llm.model_store(), expected)


if __name__ == "__main__":
    unittest.main()
