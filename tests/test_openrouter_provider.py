import ctypes
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from engine import storage


class OpenRouterSettingsContractTests(unittest.TestCase):
    def test_defaults_keep_online_chat_off_and_choose_free_router(self):
        self.assertEqual(storage.DEFAULT_SETTINGS['chat_provider'], 'local')
        self.assertFalse(storage.DEFAULT_SETTINGS['openrouter_allow_online'])
        self.assertEqual(storage.DEFAULT_SETTINGS['openrouter_chat_model'], 'openrouter/free')

    def test_settings_coercion_rejects_unknown_provider(self):
        coerced = storage._coerce_settings({'chat_provider': 'mystery', 'openrouter_allow_online': 'yes'})
        self.assertEqual(coerced['chat_provider'], 'local')
        self.assertIs(coerced['openrouter_allow_online'], True)


class OpenRouterProviderContractTests(unittest.TestCase):
    def test_catalog_contains_current_verified_free_models_only(self):
        from engine import openrouter
        by_id = {row['id']: row for row in openrouter.list_models()}
        self.assertIn('openrouter/free', by_id)
        self.assertIn('nvidia/nemotron-3-ultra-550b-a55b:free', by_id)
        self.assertIn('deepseek/deepseek-v4-flash-0731:free', by_id)
        self.assertIn('qwen/qwen3.8-27b:free', by_id)
        self.assertIn('thinkingmachines/inkling-small:free', by_id)
        self.assertIn('nvidia/nemotron-3-super-120b-a12b:free', by_id)
        self.assertNotIn('z-ai/glm-5.3-flash:free', by_id)
        self.assertNotIn('qwen/qwen3-235b-a22b-2507:free', by_id)
        self.assertNotIn('thinkingmachines/inkling:free', by_id)
        self.assertNotIn('nvidia/nemotron-3-super:free', by_id)
        self.assertTrue(by_id['openrouter/free']['free'])
        self.assertTrue(by_id['nvidia/nemotron-3-ultra-550b-a55b:free']['free'])
        self.assertTrue(by_id['deepseek/deepseek-v4-flash-0731:free']['free'])

    def test_legacy_same_model_slugs_migrate_without_changing_model_identity(self):
        from engine import openrouter
        self.assertEqual(
            openrouter.validate_model('thinkingmachines/inkling:free'),
            'thinkingmachines/inkling-small:free',
        )
        self.assertEqual(
            openrouter.validate_model('nvidia/nemotron-3-super:free'),
            'nvidia/nemotron-3-super-120b-a12b:free',
        )

    def test_retired_free_endpoints_do_not_silently_switch_to_paid_models(self):
        from engine import openrouter
        with self.assertRaises(ValueError):
            openrouter.validate_model('z-ai/glm-5.3-flash:free')
        with self.assertRaises(ValueError):
            openrouter.validate_model('qwen/qwen3-235b-a22b-2507:free')

    def test_kimi_is_available_but_marked_paid(self):
        from engine import openrouter
        row = next(x for x in openrouter.list_models() if x['id'] == 'moonshotai/kimi-k2.5')
        self.assertFalse(row['free'])
        self.assertIn('Kimi', row['name'])

    def test_model_specs_round_trip_without_confusing_free_suffix(self):
        from engine import openrouter
        slug = 'deepseek/deepseek-v4-flash-0731:free'
        encoded = openrouter.encode_model(slug)
        self.assertTrue(openrouter.is_openrouter_model(encoded))
        self.assertEqual(openrouter.decode_model(encoded), slug)

    def test_environment_key_is_supported_without_persisting_secret(self):
        from engine import openrouter
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'sk-or-v1-testvalue'}, clear=False):
            status = openrouter.key_status()
            self.assertTrue(status['configured'])
            self.assertEqual(status['source'], 'environment')
            self.assertNotIn('sk-or-v1-testvalue', repr(status))

    def test_stream_request_uses_openrouter_schema_without_internal_session_id(self):
        from engine import openrouter

        captured = {}

        class FakeResponse:
            ok = True
            status_code = 200
            text = ''
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def iter_lines(self, decode_unicode=True):
                yield 'data: {"model":"deepseek/deepseek-v4-flash-0731:free","choices":[{"delta":{"content":"hello"},"finish_reason":null}]}'
                yield 'data: {"usage":{"prompt_tokens":4,"completion_tokens":1,"total_tokens":5},"choices":[{"delta":{},"finish_reason":"stop"}]}'
                yield 'data: [DONE]'

        def fake_post(url, **kwargs):
            captured.update(kwargs)
            captured['url'] = url
            return FakeResponse()

        settings = {'openrouter_allow_online': True, 'think_mode': 'auto', 'chat_temperature': 0.2, 'ollama_num_predict': 128}
        spec = openrouter.encode_model('deepseek/deepseek-v4-flash-0731:free')
        with patch.object(openrouter, 'load_api_key', return_value='sk-or-v1-testvalue'), patch.object(openrouter.requests, 'post', side_effect=fake_post):
            events = list(openrouter.stream_chat(settings, [{'role':'user','content':'hi'}], model_override=spec, session_id='internal-private-id'))

        self.assertEqual(captured['url'], 'https://openrouter.ai/api/v1/chat/completions')
        self.assertNotIn('session_id', captured['json'])
        self.assertEqual(captured['json']['model'], 'deepseek/deepseek-v4-flash-0731:free')
        self.assertIn(('content', 'hello'), events)
        self.assertEqual(events[-1][0], 'stats')
        self.assertEqual(events[-1][1]['total_tokens'], 5)

    def test_public_status_never_contains_api_key_material(self):
        from engine import openrouter
        with patch.object(openrouter, 'load_api_key', return_value='sk-or-v1-hidden'), patch.object(openrouter, '_env_key', return_value=''):
            status = openrouter.public_status({'openrouter_allow_online': True})
        self.assertTrue(status['configured'])
        self.assertNotIn('sk-or-v1-hidden', repr(status))
        self.assertNotIn('api_key', status)

    def test_dpapi_protect_uses_explicit_wide_description(self):
        from engine import openrouter

        seen = {}

        class FakeFunction:
            def __init__(self, callback):
                self.callback = callback
                self.argtypes = None
                self.restype = None
            def __call__(self, *args):
                return self.callback(*args)

        def protect(_in_blob, description, _entropy, _reserved, _prompt, _flags, _out_blob):
            seen['description'] = description
            return 1

        fake_windll = SimpleNamespace(
            crypt32=SimpleNamespace(CryptProtectData=FakeFunction(protect), CryptUnprotectData=FakeFunction(lambda *_args: 1)),
            kernel32=SimpleNamespace(LocalFree=FakeFunction(lambda _ptr: None)),
        )
        with patch.object(openrouter.os, 'name', 'nt'), \
             patch.object(openrouter.ctypes, 'windll', fake_windll, create=True), \
             patch.object(openrouter.ctypes, 'string_at', return_value=b'protected'):
            protected = openrouter._protect_windows(b'secret')

        self.assertEqual(protected, b'protected')
        self.assertIsInstance(seen['description'], ctypes.c_wchar_p)


class OpenRouterErrorContractTests(unittest.TestCase):
    def test_unavailable_openrouter_model_gets_specific_recovery_message(self):
        import server
        code, message = server._friendly_generation_error(
            RuntimeError('OpenRouter HTTP 404: {"error":{"message":"No endpoints found for model"}}')
        )
        self.assertEqual(code, 'openrouter_model_unavailable')
        self.assertIn('no longer available', message.lower())
        self.assertIn('new chat', message.lower())

    def test_retired_catalog_slug_gets_same_specific_recovery_message(self):
        import server
        code, message = server._friendly_generation_error(
            ValueError("That OpenRouter model is unavailable or no longer in MatrixStudio's current catalog.")
        )
        self.assertEqual(code, 'openrouter_model_unavailable')
        self.assertIn('new chat', message.lower())


class OpenRouterServerSecurityTests(unittest.TestCase):
    def test_key_save_response_never_uses_a_key_field(self):
        import server
        with patch.object(server.openrouter, 'save_api_key', return_value={'configured': True}), patch.object(server.openrouter, 'public_status', return_value={'configured': True}):
            result = server.openrouter_key_save(server.OpenRouterKeyBody(api_key='sk-or-v1-testvalue-long-enough'))
        self.assertNotIn('key', result)
        self.assertEqual(result['status']['configured'], True)

    def test_saved_openrouter_secret_is_gitignored(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        gitignore = (root / '.gitignore').read_text(encoding='utf-8')
        self.assertIn('data/openrouter.secret.json', gitignore)


class OpenRouterUIContractTests(unittest.TestCase):
    def test_runtime_ui_has_online_provider_controls(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        html = (root / 'templates' / 'index.html').read_text(encoding='utf-8')
        js = (root / 'static' / 'js' / 'app.js').read_text(encoding='utf-8')
        self.assertIn('id="set-chat-provider"', html)
        self.assertIn('id="set-openrouter-model"', html)
        self.assertIn('id="set-openrouter-key"', html)
        self.assertIn('id="save-openrouter-key"', html)
        self.assertIn('/api/openrouter/key', js)
        self.assertIn('/api/openrouter/status', js)
        self.assertIn('id="openrouter-action-status"', html)
        self.assertIn('setOpenRouterActionStatus(', js)
        # The raw key must be handled by its own endpoint, never settings autosave.
        self.assertNotIn('openrouter_api_key:', js)

    def test_runtime_readiness_uses_selected_chat_provider_not_only_local_ollama(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        js = (root / 'static' / 'js' / 'app.js').read_text(encoding='utf-8')
        self.assertIn('const chatReady = chatModelUsable(sessionGenerationProfile().model);', js)
        self.assertIn("$('#send-chat').disabled = !chatReady || !!state.abort;", js)
        self.assertIn("$('#messages').classList.toggle('has-alert', !chatReady);", js)

    def test_provider_autosave_updates_unlocked_empty_session_model(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        js = (root / 'static' / 'js' / 'app.js').read_text(encoding='utf-8')
        self.assertIn('async function syncEmptySessionDefaultModel()', js)
        self.assertIn('await syncEmptySessionDefaultModel();', js)


if __name__ == '__main__':
    unittest.main()
