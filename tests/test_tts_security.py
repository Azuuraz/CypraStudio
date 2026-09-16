import unittest


class TTSSecurityTests(unittest.TestCase):
    def test_online_tts_redacts_credentials_and_internal_context(self):
        from tts.sanitizer import sanitize_for_online_tts

        raw = "SYSTEM_PROMPT: hidden rules\nAuthorization: Bearer abcdef1234567890\nSay hello to Azu."
        safe = sanitize_for_online_tts(raw)
        low = safe.lower()
        self.assertNotIn("hidden rules", low)
        self.assertNotIn("abcdef1234567890", safe)
        self.assertIn("hello", low)

    def test_speech_cleanup_omits_code_urls_and_metadata(self):
        from tts.sanitizer import sanitize_for_speech

        raw = "Answer.\n```python\nprint('secret')\n```\nhttps://example.com/a\nTokens: 999\nDone."
        safe = sanitize_for_speech(raw, maximum=1000, skip_code=True, skip_urls=True)
        self.assertNotIn("print", safe)
        self.assertNotIn("https://", safe)
        self.assertNotIn("999", safe)
        self.assertIn("Answer", safe)
        self.assertIn("Done", safe)

    def test_edge_voice_name_is_bounded_to_expected_shape(self):
        from tts.policy import normalize_edge_voice

        self.assertEqual(normalize_edge_voice("en-US-AvaNeural"), "en-US-AvaNeural")
        self.assertEqual(normalize_edge_voice("../../bad"), "en-US-AvaNeural")
        self.assertEqual(normalize_edge_voice("x" * 200), "en-US-AvaNeural")


if __name__ == "__main__":
    unittest.main()
