from pathlib import Path
import unittest

from tts.expression import build_speech_plan, normalize_expression_detail, resolve_edge_prosody, resolve_tone


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


    def test_expression_presets_are_audibly_stronger_at_default_intensity(self):
        cheerful = resolve_edge_prosody('cheerful', intensity=0.7, speed=1.0, pitch=1.0, volume=1.0, text='Great news!')
        sad = resolve_edge_prosody('sad', intensity=0.7, speed=1.0, pitch=1.0, volume=1.0, text='Unfortunately, this failed.')

        self.assertGreaterEqual(int(cheerful['rate'].rstrip('%')), 10)
        self.assertGreaterEqual(int(cheerful['pitch'].rstrip('Hz')), 10)
        self.assertLessEqual(int(sad['rate'].rstrip('%')), -12)
        self.assertLessEqual(int(sad['pitch'].rstrip('Hz')), -12)

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

    def test_automatic_pause_styles_keep_normal_speech_to_one_edge_request(self):
        source = 'One sentence. Two sentence, with detail.'
        natural = build_speech_plan(source, style='natural', maximum_segments=24)
        expressive = build_speech_plan(source, style='expressive', maximum_segments=24)
        off = build_speech_plan(source, style='off', maximum_segments=24)

        self.assertEqual(len(natural), 1)
        self.assertEqual(len(expressive), 1)
        self.assertEqual(natural[0]['pause_after_ms'], 0)
        self.assertEqual(expressive[0]['pause_after_ms'], 0)
        self.assertNotEqual(expressive[0]['text'], off[0]['text'])
        self.assertEqual(off, [{'text': source, 'pause_after_ms': 0}])

    def test_manual_pause_markers_are_the_only_automatic_reason_to_split_requests(self):
        plan = build_speech_plan('First sentence. [pause:650] Second sentence.', style='expressive', maximum_segments=24)
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[0]['pause_after_ms'], 650)
        self.assertEqual(plan[1]['pause_after_ms'], 0)

    def test_pause_plan_is_bounded(self):
        text = ' '.join(f'Part {i}.' for i in range(100))
        plan = build_speech_plan(text, style='expressive', maximum_segments=12)
        self.assertEqual(len(plan), 1)
        self.assertTrue(plan[0]['text'].strip())


    def test_expression_detail_normalizer_is_bounded(self):
        self.assertEqual(normalize_expression_detail('LIVELY'), 'lively')
        self.assertEqual(normalize_expression_detail('subtle'), 'subtle')
        self.assertEqual(normalize_expression_detail('wat'), 'natural')

    def test_expression_detail_changes_single_request_punctuation_shaping(self):
        source = 'Wait — are you sure? Yes! This matters.'
        subtle = build_speech_plan(source, style='expressive', detail='subtle')
        natural = build_speech_plan(source, style='expressive', detail='natural')
        lively = build_speech_plan(source, style='expressive', detail='lively')
        self.assertEqual(len(subtle), 1)
        self.assertEqual(len(natural), 1)
        self.assertEqual(len(lively), 1)
        self.assertNotEqual(subtle[0]['text'], lively[0]['text'])
        self.assertGreater(lively[0]['text'].count('…'), subtle[0]['text'].count('…'))

    def test_inline_expression_cues_create_bounded_overrides_without_being_spoken(self):
        plan = build_speech_plan(
            'Start normal. [soft] Keep this gentle. [pause:450] [excited] Great news! [slow] Carefully now. [normal] Back to normal.',
            style='natural', detail='natural', maximum_segments=24,
        )
        joined = ' '.join(str(item['text']) for item in plan)
        for cue in ('[soft]', '[excited]', '[slow]', '[normal]', '[pause:450]'):
            self.assertNotIn(cue, joined)
        self.assertGreaterEqual(len(plan), 4)
        soft = next(item for item in plan if 'gentle' in item['text'])
        excited = next(item for item in plan if 'Great news' in item['text'])
        slow = next(item for item in plan if 'Carefully' in item['text'])
        reset = next(item for item in plan if 'Back to normal' in item['text'])
        self.assertEqual(soft['tone'], 'calm')
        self.assertLess(float(soft['rate_scale']), 1.0)
        self.assertEqual(excited['tone'], 'cheerful')
        self.assertGreater(float(excited['rate_scale']), 1.0)
        self.assertLess(float(slow['rate_scale']), 1.0)
        self.assertIsNone(reset['tone'])
        self.assertEqual(float(reset['rate_scale']), 1.0)
        pause_owner = next(item for item in plan if item['pause_after_ms'])
        self.assertEqual(pause_owner['pause_after_ms'], 450)

    def test_emphasis_and_speed_cues_stay_local_and_bounded(self):
        plan = build_speech_plan('[emphasis] Important. [fast] Move. [serious] Verify. [normal] Done.', detail='lively')
        self.assertLessEqual(len(plan), 8)
        emphasized = next(item for item in plan if 'Important' in item['text'])
        fast = next(item for item in plan if 'Move' in item['text'])
        serious = next(item for item in plan if 'Verify' in item['text'])
        self.assertGreater(float(emphasized['volume_scale']), 1.0)
        self.assertGreater(float(fast['rate_scale']), 1.0)
        self.assertEqual(serious['tone'], 'serious')

    def test_settings_expression_normalizers_are_bounded(self):
        from tts.expression import normalize_pause_style, normalize_tone
        self.assertEqual(normalize_tone('ANGRY'), 'angry')
        self.assertEqual(normalize_tone('unsupported'), 'neutral')
        self.assertEqual(normalize_pause_style('expressive'), 'expressive')
        self.assertEqual(normalize_pause_style('unsupported'), 'natural')


if __name__ == '__main__':
    unittest.main()
