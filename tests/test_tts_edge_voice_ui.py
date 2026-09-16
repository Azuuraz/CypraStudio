from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TTSEdgeVoiceUIContractTests(unittest.TestCase):
    def test_edge_voice_is_dynamic_selector_not_free_text(self):
        html = (ROOT / 'templates' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="tts-edge-voice-field"', html)
        self.assertIn('id="tts-local-voice-field"', html)
        self.assertIn('<select id="set-tts-edge-voice"', html)
        self.assertNotIn('<input id="set-tts-edge-voice"', html)
        self.assertIn('id="refresh-edge-voices"', html)
        self.assertIn('id="edge-voice-status"', html)

    def test_client_swaps_provider_controls_and_loads_edge_voice_catalog(self):
        js = (ROOT / 'static' / 'js' / 'app.js').read_text(encoding='utf-8')
        self.assertIn('function syncTTSProviderUI()', js)
        self.assertIn('async function loadEdgeVoices', js)
        self.assertIn("'/api/tts/voices/edge'", js)
        self.assertIn("'/api/tts/edge/prepare'", js)
        self.assertIn("$('#tts-edge-voice-field').hidden = provider !== 'edge'", js)
        self.assertIn("$('#tts-local-voice-field').hidden = provider !== 'local'", js)
        self.assertIn('await loadEdgeVoices({force:true})', js)

    def test_edge_catalog_labels_include_locale_and_gender(self):
        js = (ROOT / 'static' / 'js' / 'app.js').read_text(encoding='utf-8')
        self.assertIn('friendly_name', js)
        self.assertIn('short_name', js)
        self.assertIn('locale', js)
        self.assertIn('gender', js)


if __name__ == '__main__':
    unittest.main()
