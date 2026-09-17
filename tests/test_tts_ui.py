from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TTSUIContractTests(unittest.TestCase):
    def test_settings_surface_exposes_voice_controls(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        for marker in (
            'data-tab="voice"',
            'data-page="voice"',
            'id="set-voice-output"',
            'id="set-tts-provider"',
            'id="set-tts-allow-online"',
            'id="set-tts-auto-speak"',
            'id="voice-preview"',
            'id="voice-stop"',
        ):
            self.assertIn(marker, html)

    def test_client_supports_browser_fallback_and_speak_action(self):
        js = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function sanitizeBrowserSpeech", js)
        self.assertIn("async function speakText", js)
        self.assertIn("speechSynthesis.cancel()", js)
        self.assertIn("/api/tts", js)
        self.assertIn("speak.textContent = 'SPEAK'", js)


if __name__ == "__main__":
    unittest.main()
