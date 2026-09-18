import types
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from tts.engines.edge_engine import EdgeEngine
from tts.service import SynthesisResult


class TTSEdgeExpressionAPITests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, base_url='http://127.0.0.1:8765', client=('127.0.0.1', 50124))

    def test_synthesis_request_forwards_bounded_expression_controls(self):
        settings = {
            'voice_output_enabled': True,
            'tts_provider': 'edge',
            'tts_allow_online': True,
            'tts_edge_voice': 'en-US-AvaNeural',
            'tts_online_fallback': 'none',
            'tts_rate': 1.0,
            'tts_pitch': 1.0,
            'tts_volume': 1.0,
            'tts_tone': 'neutral',
            'tts_intensity': 0.7,
            'tts_cpu_threads': 2,
            'tts_max_chars': 1200,
            'tts_skip_code': True,
            'tts_skip_urls': True,
            'tts_stop_previous': True,
            'tts_local_voice': 'en_US-lessac-medium',
        }
        with patch('server.load_settings', return_value=settings), \
             patch.object(server.LOCAL_TTS, 'synthesize_result', return_value=SynthesisResult(b'x' * 64, 'audio/mpeg', 'edge')) as synth:
            response = self.client.post('/api/tts', json={
                'text': 'Great news!', 'provider': 'edge', 'voice_id': 'en-US-AvaNeural',
                'rate': 1.1, 'pitch': 1.2, 'volume': 1.15, 'tone': 'cheerful', 'intensity': 0.8,
            })
        self.assertEqual(response.status_code, 200)
        kwargs = synth.call_args.kwargs
        self.assertEqual(kwargs['speed'], 1.1)
        self.assertEqual(kwargs['pitch'], 1.2)
        self.assertEqual(kwargs['volume'], 1.15)
        self.assertEqual(kwargs['tone'], 'cheerful')
        self.assertEqual(kwargs['intensity'], 0.8)

    def test_edge_plan_redacts_credentials_before_segments_are_returned(self):
        settings = {
            'tts_allow_online': True, 'tts_tone': 'neutral', 'tts_intensity': 0.7,
            'tts_pause_style': 'natural', 'tts_max_chars': 1200,
            'tts_skip_code': True, 'tts_skip_urls': True,
        }
        with patch('server.load_settings', return_value=settings):
            response = self.client.post('/api/tts/plan', json={'text': 'TOKEN=supersecretvalue. Hello there.'})
        self.assertEqual(response.status_code, 200)
        spoken = ' '.join(item['text'] for item in response.json()['segments']).lower()
        self.assertNotIn('supersecretvalue', spoken)
        self.assertIn('hello there', spoken)


class EdgeEngineProsodyTests(unittest.IsolatedAsyncioTestCase):
    async def test_edge_retries_transport_failure_once(self):
        attempts = 0
        class FakeCommunicate:
            def __init__(self, *args, **kwargs):
                pass
            async def stream(self):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise OSError('connection reset')
                yield {'type': 'audio', 'data': b'a' * 64}
        with patch.dict('sys.modules', {'edge_tts': types.SimpleNamespace(Communicate=FakeCommunicate)}):
            audio = await EdgeEngine().synthesize('Hello', voice='en-US-AvaNeural', cancelled=lambda: False)
        self.assertEqual(audio, b'a' * 64)
        self.assertEqual(attempts, 2)

    async def test_edge_does_not_retry_malformed_audio(self):
        attempts = 0
        class FakeCommunicate:
            def __init__(self, *args, **kwargs):
                pass
            async def stream(self):
                nonlocal attempts
                attempts += 1
                yield {'type': 'audio', 'data': 'not bytes'}
        with patch.dict('sys.modules', {'edge_tts': types.SimpleNamespace(Communicate=FakeCommunicate)}):
            with self.assertRaisesRegex(Exception, 'malformed audio'):
                await EdgeEngine().synthesize('Hello', voice='en-US-AvaNeural', cancelled=lambda: False)
        self.assertEqual(attempts, 1)

    async def test_edge_engine_forwards_rate_pitch_and_volume_to_communicate(self):
        captured = {}

        class FakeCommunicate:
            def __init__(self, text, voice, **kwargs):
                captured.update({'text': text, 'voice': voice, **kwargs})

            async def stream(self):
                yield {'type': 'audio', 'data': b'a' * 64}

        fake_module = types.SimpleNamespace(Communicate=FakeCommunicate)
        with patch.dict('sys.modules', {'edge_tts': fake_module}):
            audio = await EdgeEngine().synthesize(
                'Hello', voice='en-US-AvaNeural', rate='+8%', pitch='+6Hz', volume='+4%',
                cancelled=lambda: False,
            )
        self.assertEqual(audio, b'a' * 64)
        self.assertEqual(captured['rate'], '+8%')
        self.assertEqual(captured['pitch'], '+6Hz')
        self.assertEqual(captured['volume'], '+4%')


if __name__ == '__main__':
    unittest.main()
