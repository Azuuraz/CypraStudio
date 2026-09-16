from pathlib import Path
import unittest

from tts.expression import build_speech_plan, resolve_edge_prosody, resolve_tone


class TTSExpressionTests(unittest.TestCase):
    def test_tone_presets_adjust_edge_prosody_without_discarding_manual_controls(self):
        neutral = resolve_edge_prosody('neutral', intensity=1.0, speed=1.0, pitch=1.0, volume=1.0, text='Hello.')
        cheerful = resolve_edge_prosody('cheerful', intensity=1.0, speed=1.0, pitch=1.0, volume=1.0, text='Great news!')
        manual = resolve_edge_prosody('neutral', intensity=1.0, speed=1.10, pitch=1.25, volume=0.90, text='Hello.')

        self.assertEqual(neutral['tone'], 'neutral')
        self.assertEqual(neutral['rate'], '+0%')
        self.assertEqual(neutral['pitch'], '+0Hz')
        self.assertEqual(neutral['volume'], '+0%')
        self.assertEqual(cheerful['tone'], 'cheerful')
        self.assertGreater(int(cheerful['rate'].rstrip('%')), 0)
        self.assertGreater(int(cheerful['pitch'].rstrip('Hz')), 0)
        self.assertGreater(int(cheerful['volume'].rstrip('%')), 0)
        self.assertEqual(manual['rate'], '+10%')
        self.assertEqual(manual['pitch'], '+5Hz')
        self.assertEqual(manual['volume'], '-10%')

    def test_auto_tone_is_local_deterministic_and_conservative(self):
        self.assertEqual(resolve_tone('auto', 'Warning: a critical security check failed.'), 'serious')
        self.assertEqual(resolve_tone('auto', 'Great, that worked successfully!'), 'cheerful')
        self.assertEqual(resolve_tone('auto', 'Unfortunately, that result could not be recovered.'), 'sad')
        self.assertEqual(resolve_tone('auto', 'Here are the steps to configure the runtime safely.'), 'narrator')

    def test_pause_plan_honors_manual_pauses_and_caps_them(self):
        plan = build_speech_plan('First line. [pause:9999] Second line.', style='natural', maximum_segments=24)
        self.assertGreaterEqual(len(plan), 2)
        self.assertEqual(plan[0]['text'], 'First line.')
        self.assertEqual(plan[0]['pause_after_ms'], 2000)
        self.assertEqual(plan[1]['text'], 'Second line.')

    def test_pause_styles_create_real_segment_boundaries_but_off_disables_automatic_pauses(self):
        natural = build_speech_plan('One sentence. Two sentence, with detail.', style='natural', maximum_segments=24)
        expressive = build_speech_plan('One sentence. Two sentence, with detail.', style='expressive', maximum_segments=24)
        off = build_speech_plan('One sentence. Two sentence, with detail.', style='off', maximum_segments=24)
        self.assertGreater(len(natural), 1)
        self.assertGreater(max(item['pause_after_ms'] for item in expressive), max(item['pause_after_ms'] for item in natural))
        self.assertEqual(off, [{'text': 'One sentence. Two sentence, with detail.', 'pause_after_ms': 0}])

    def test_pause_plan_is_bounded(self):
        text = ' '.join(f'Part {i}.' for i in range(100))
        plan = build_speech_plan(text, style='expressive', maximum_segments=12)
        self.assertLessEqual(len(plan), 12)
        self.assertTrue(all(item['text'].strip() for item in plan))

    def test_settings_expression_normalizers_are_bounded(self):
        from tts.expression import normalize_pause_style, normalize_tone
        self.assertEqual(normalize_tone('ANGRY'), 'angry')
        self.assertEqual(normalize_tone('unsupported'), 'neutral')
        self.assertEqual(normalize_pause_style('expressive'), 'expressive')
        self.assertEqual(normalize_pause_style('unsupported'), 'natural')


if __name__ == '__main__':
    unittest.main()
