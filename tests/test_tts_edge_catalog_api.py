import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import server


class TTSEdgeCatalogAPITests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, base_url='http://127.0.0.1:8765', client=('127.0.0.1', 50124))

    def test_edge_voice_catalog_stays_behind_online_gate(self):
        with patch('server.load_settings', return_value={'tts_allow_online': False}):
            response = self.client.get('/api/tts/voices/edge')
        self.assertEqual(response.status_code, 409)

    def test_refresh_requests_fresh_full_catalog(self):
        voices = [
            {'short_name': 'en-US-AvaNeural', 'locale': 'en-US', 'gender': 'Female', 'friendly_name': 'Microsoft Ava Online (Natural)'},
            {'short_name': 'en-GB-SoniaNeural', 'locale': 'en-GB', 'gender': 'Female', 'friendly_name': 'Microsoft Sonia Online (Natural)'},
        ]
        with patch('server.load_settings', return_value={'tts_allow_online': True}), patch.object(server.LOCAL_TTS, 'prepare_edge_dependency', return_value=True), patch.object(server.LOCAL_TTS, 'edge_voices', return_value=voices) as discover:
            response = self.client.get('/api/tts/voices/edge?refresh=1')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['count'], 2)
        self.assertEqual(body['voices'], voices)
        discover.assert_called_once_with(refresh=True)

    def test_edge_plan_stays_behind_online_gate_and_returns_bounded_segments(self):
        with patch('server.load_settings', return_value={'tts_allow_online': False}):
            blocked = self.client.post('/api/tts/plan', json={'text': 'Hello. World.'})
        self.assertEqual(blocked.status_code, 409)

        settings = {
            'tts_allow_online': True, 'tts_tone': 'dramatic', 'tts_intensity': 0.8,
            'tts_pause_style': 'expressive', 'tts_max_chars': 1200,
            'tts_skip_code': True, 'tts_skip_urls': True,
        }
        with patch('server.load_settings', return_value=settings):
            response = self.client.post('/api/tts/plan', json={'text': 'First. [pause:500] Second.'})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['tone'], 'dramatic')
        self.assertGreaterEqual(len(body['segments']), 2)
        self.assertTrue(all(0 <= int(item['pause_after_ms']) <= 2000 for item in body['segments']))


if __name__ == '__main__':
    unittest.main()
