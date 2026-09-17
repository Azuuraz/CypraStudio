from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TTSExpressionUIContractTests(unittest.TestCase):
    def test_voice_settings_expose_expression_controls(self):
        html = (ROOT / 'templates' / 'index.html').read_text(encoding='utf-8')
        for control in ('set-tts-tone', 'set-tts-intensity', 'set-tts-volume', 'set-tts-pause-style'):
            self.assertIn(f'id="{control}"', html)
        for tone in ('neutral', 'calm', 'friendly', 'cheerful', 'serious', 'sad', 'angry', 'dramatic', 'narrator', 'auto'):
            self.assertIn(f'value="{tone}"', html)

    def test_edge_client_requests_a_pause_plan_and_plays_segments_in_order(self):
        js = (ROOT / 'static' / 'js' / 'app.js').read_text(encoding='utf-8')
        self.assertIn("'/api/tts/plan'", js)
        self.assertIn('pause_after_ms', js)
        self.assertIn('for (let index = 0; index < speechSegments.length; index += 1)', js)
        self.assertIn('await waitSpeechPause', js)
        self.assertIn('tone:', js)
        self.assertIn('intensity:', js)


if __name__ == '__main__':
    unittest.main()
