import unittest

from engine import storage


class TTSSettingsTests(unittest.TestCase):
    def test_voice_defaults_are_private_and_disabled(self):
        settings = storage._coerce_settings({})
        self.assertFalse(settings["voice_output_enabled"])
        self.assertEqual(settings["tts_provider"], "browser")
        self.assertFalse(settings["tts_allow_online"])
        self.assertEqual(settings["tts_edge_voice"], "en-US-AvaNeural")

    def test_tts_settings_are_bounded_and_invalid_voice_is_replaced(self):
        settings = storage._coerce_settings({
            "voice_output_enabled": "yes",
            "tts_provider": "edge",
            "tts_allow_online": True,
            "tts_edge_voice": "../../escape",
            "tts_rate": 99,
            "tts_pitch": -5,
            "tts_max_chars": 999999,
            "tts_cpu_threads": 99,
            "tts_online_fallback": "wat",
        })
        self.assertTrue(settings["voice_output_enabled"])
        self.assertEqual(settings["tts_provider"], "edge")
        self.assertTrue(settings["tts_allow_online"])
        self.assertEqual(settings["tts_edge_voice"], "en-US-AvaNeural")
        self.assertEqual(settings["tts_rate"], 2.0)
        self.assertEqual(settings["tts_pitch"], 0.5)
        self.assertEqual(settings["tts_max_chars"], 50000)
        self.assertEqual(settings["tts_cpu_threads"], 4)
        self.assertEqual(settings["tts_online_fallback"], "browser")

    def test_point2_factory_1200_limit_migrates_to_full_response(self):
        migrated = storage._coerce_settings({"settings_schema": 12, "tts_max_chars": 1200})
        self.assertEqual(migrated["tts_max_chars"], 50000)

        custom = storage._coerce_settings({"settings_schema": 12, "tts_max_chars": 5000})
        self.assertEqual(custom["tts_max_chars"], 5000)

    def test_expression_defaults_and_bounds(self):
        defaults = storage._coerce_settings({})
        self.assertEqual(defaults["tts_tone"], "neutral")
        self.assertEqual(defaults["tts_pause_style"], "natural")
        self.assertEqual(defaults["tts_intensity"], 0.7)
        self.assertEqual(defaults["tts_volume"], 1.0)

        bounded = storage._coerce_settings({
            "tts_tone": "ANGRY",
            "tts_pause_style": "expressive",
            "tts_intensity": 99,
            "tts_volume": -2,
        })
        self.assertEqual(bounded["tts_tone"], "angry")
        self.assertEqual(bounded["tts_pause_style"], "expressive")
        self.assertEqual(bounded["tts_intensity"], 1.0)
        self.assertEqual(bounded["tts_volume"], 0.5)


if __name__ == "__main__":
    unittest.main()
