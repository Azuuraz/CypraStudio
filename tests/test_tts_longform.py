from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from engine import storage
from tts.expression import build_speech_plan
from tts.sanitizer import sanitize_for_speech

ROOT = Path(__file__).resolve().parents[1]


class TTSLongFormSettingsTests(unittest.TestCase):
    def test_full_response_is_default_with_50000_character_hard_ceiling(self):
        defaults = storage._coerce_settings({})
        self.assertEqual(defaults['tts_max_chars'], 50000)

        bounded = storage._coerce_settings({'tts_max_chars': 999999})
        self.assertEqual(bounded['tts_max_chars'], 50000)

    def test_speech_sanitizer_no_longer_has_hidden_10000_character_ceiling(self):
        text = ('Long form speech sentence. ' * 600).strip()
        self.assertGreater(len(text), 10000)
        spoken = sanitize_for_speech(text, maximum=50000)
        self.assertGreater(len(spoken), 10000)
        self.assertEqual(spoken, text)


class TTSLongFormPlanningTests(unittest.TestCase):
    def test_fast_opening_preserves_every_word_and_manual_pause(self):
        text = ' '.join(f'Sentence {i:04d} contains enough words for natural speech.' for i in range(150))
        plan = build_speech_plan(text + ' [pause:900] Done.', first_chunk_chars=600)
        self.assertLessEqual(len(plan[0]['text']), 600)
        self.assertTrue(plan[0]['text'].endswith('.'))
        self.assertGreater(len(plan[1]['text']), 600)
        self.assertEqual(' '.join(item['text'] for item in plan), text + ' Done.')
        self.assertEqual(plan[-2]['pause_after_ms'], 900)

    def test_long_ordinary_speech_is_chunked_at_sentence_boundaries(self):
        text = ' '.join(f'Sentence {i:04d} contains enough words for long form Edge speech.' for i in range(220))
        plan = build_speech_plan(text, style='natural', maximum_segments=48, maximum_chunk_chars=3200)
        self.assertGreater(len(plan), 1)
        self.assertLessEqual(len(plan), 48)
        self.assertTrue(all(0 < len(str(item['text'])) <= 3200 for item in plan))
        rebuilt = ' '.join(str(item['text']) for item in plan)
        self.assertIn('Sentence 0000', rebuilt)
        self.assertIn('Sentence 0219', rebuilt)

    def test_manual_pause_stays_on_last_chunk_before_the_pause(self):
        left = ' '.join(f'Before pause sentence {i:04d}.' for i in range(220))
        right = 'After the pause, speech continues normally.'
        plan = build_speech_plan(f'{left} [pause:900] {right}', style='natural', maximum_segments=48, maximum_chunk_chars=3200)
        pause_items = [item for item in plan if int(item['pause_after_ms']) == 900]
        self.assertEqual(len(pause_items), 1)
        self.assertIn('Before pause sentence 0219.', str(pause_items[0]['text']))
        self.assertIn(right, str(plan[-1]['text']))


class TTSLongFormAPITests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, base_url='http://127.0.0.1:8765', client=('127.0.0.1', 50124))

    def test_plan_keeps_long_response_through_final_sentence(self):
        settings = {
            'tts_allow_online': True,
            'tts_tone': 'neutral',
            'tts_intensity': 0.7,
            'tts_pause_style': 'natural',
            'tts_max_chars': 50000,
            'tts_skip_code': True,
            'tts_skip_urls': True,
        }
        text = ' '.join(f'Long response sentence {i:04d} is preserved.' for i in range(350))
        with patch('server.load_settings', return_value=settings):
            response = self.client.post('/api/tts/plan', json={'text': text})
        self.assertEqual(response.status_code, 200)
        segments = response.json()['segments']
        self.assertLessEqual(len(segments[0]['text']), 600)
        self.assertGreater(len(segments), 1)
        self.assertTrue(all(len(item['text']) <= 3200 for item in segments))
        joined = ' '.join(item['text'] for item in segments)
        self.assertIn('Long response sentence 0349 is preserved.', joined)


class TTSLongFormUIContractTests(unittest.TestCase):
    def test_voice_settings_show_full_response_hard_ceiling(self):
        html = (ROOT / 'templates' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('max="50000"', html)
        self.assertIn('50,000', html)

    def test_edge_client_prefetches_next_long_form_chunk(self):
        js = (ROOT / 'static' / 'js' / 'app.js').read_text(encoding='utf-8')
        self.assertIn('TTS_HARD_CEILING = 50000', js)
        self.assertIn('prefetchEdgeSegment', js)
        self.assertIn('pendingSpeech', js)


if __name__ == '__main__':
    unittest.main()
