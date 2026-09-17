from pathlib import Path
import io
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from engine import storage

ROOT = Path(__file__).resolve().parents[1]


class STTSettingsTests(unittest.TestCase):
    def test_local_first_browser_fallback_is_opt_in(self):
        settings = storage._coerce_settings({})
        self.assertEqual(settings["stt_provider"], "hybrid")
        self.assertFalse(settings["stt_allow_browser_online"])
        self.assertEqual(settings["stt_local_model"], "base.en")
        self.assertEqual(settings["stt_max_seconds"], 60)

    def test_stt_settings_are_bounded(self):
        settings = storage._coerce_settings({
            "stt_provider": "nonsense",
            "stt_local_model": "../../bad",
            "stt_max_seconds": 999,
        })
        self.assertEqual(settings["stt_provider"], "hybrid")
        self.assertEqual(settings["stt_local_model"], "base.en")
        self.assertEqual(settings["stt_max_seconds"], 60)


class STTAPIContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50125))

    def test_page_allows_same_origin_microphone_permission_requests(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        policy = response.headers['Permissions-Policy']
        self.assertIn('microphone=(self)', policy)
        self.assertIn('camera=()', policy)
        self.assertIn('geolocation=()', policy)

    def test_status_exposes_local_first_privacy_state(self):
        fake_status = {
            "dependency": False,
            "model_ready": False,
            "active": False,
            "model": "base.en",
            "device": "CPU",
            "compute_type": "int8",
        }
        with patch.object(server.LOCAL_STT, "status", return_value=fake_status):
            response = self.client.get("/api/stt/status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["provider"], "hybrid")
        self.assertFalse(body["allow_browser_online"])
        self.assertEqual(body["local"]["device"], "CPU")


    def test_prepare_starts_background_job_instead_of_blocking_request(self):
        fake_status = {
            "prepare_state": "installing",
            "prepare_message": "Installing local STT dependency…",
            "dependency": False,
            "model_ready": False,
            "active": False,
            "model": "base.en",
            "device": "CPU",
            "compute_type": "int8",
        }
        with patch.object(server.LOCAL_STT, "begin_prepare", return_value=fake_status) as begin:
            response = self.client.post("/api/stt/prepare")
        self.assertEqual(response.status_code, 202)
        begin.assert_called_once_with(model_name="base.en", allow_install=True, allow_download=True)
        self.assertEqual(response.json()["local"]["prepare_state"], "installing")

    def test_status_exposes_prepare_phase_and_actionable_error(self):
        fake_status = {
            "dependency": False,
            "model_ready": False,
            "active": False,
            "model": "base.en",
            "device": "CPU",
            "compute_type": "int8",
            "prepare_state": "error",
            "prepare_message": "Dependency install failed",
            "last_error": "pip could not install faster-whisper",
        }
        with patch.object(server.LOCAL_STT, "status", return_value=fake_status):
            response = self.client.get("/api/stt/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["local"]["prepare_state"], "error")
        self.assertIn("pip", response.json()["local"]["last_error"])

    def test_transcribe_accepts_bounded_webm_audio(self):
        fake_audio = b"\x1a\x45\xdf\xa3" + b"0" * 128
        with patch.object(server.LOCAL_STT, "transcribe", return_value="hello from microphone") as transcribe:
            response = self.client.post(
                "/api/stt/transcribe",
                files={"audio": ("utterance.webm", io.BytesIO(fake_audio), "audio/webm")},
                data={"duration_ms": "1200"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "hello from microphone")
        self.assertEqual(transcribe.call_count, 1)


    def test_transcribe_rejects_audio_over_60_second_hard_ceiling(self):
        fake_audio = b"\x1a\x45\xdf\xa3" + b"0" * 128
        response = self.client.post(
            "/api/stt/transcribe",
            files={"audio": ("utterance.webm", io.BytesIO(fake_audio), "audio/webm")},
            data={"duration_ms": "60001"},
        )
        self.assertEqual(response.status_code, 413)

    def test_transcribe_rejects_mislabeled_audio(self):
        response = self.client.post(
            "/api/stt/transcribe",
            files={"audio": ("utterance.webm", io.BytesIO(b"not-webm"), "audio/webm")},
            data={"duration_ms": "1200"},
        )
        self.assertEqual(response.status_code, 415)


class LiveCallUIContractTests(unittest.TestCase):
    def test_main_chat_has_live_call_and_stop_voice_controls(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="live-call"', html)
        self.assertIn('id="live-call-mute"', html)
        self.assertIn('id="stop-voice-main"', html)
        self.assertIn('id="live-call-state"', html)

    def test_voice_settings_expose_hybrid_stt_privacy_gate(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="set-stt-browser-fallback"', html)
        self.assertIn('id="prepare-local-stt"', html)
        self.assertIn('id="stt-status"', html)
        self.assertIn("Browser STT", html)

    def test_client_contains_local_capture_browser_fallback_and_continuity(self):
        js = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("MediaRecorder", js)
        self.assertIn("SpeechRecognition", js)
        self.assertIn("/api/stt/transcribe", js)
        self.assertIn("async function sendChat(forcedText = null", js)
        self.assertIn("LISTENING", js)
        self.assertIn("TRANSCRIBING", js)
        self.assertIn("THINKING", js)
        self.assertIn("SPEAKING", js)
        self.assertIn("stopSpeech({notifyBackend:true", js)
        self.assertIn("pollLocalSTTPreparation", js)
        self.assertIn("prepare_state", js)


if __name__ == "__main__":
    unittest.main()
