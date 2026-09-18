import json
import struct
import unittest
from pathlib import Path

from engine import storage


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "static" / "assets" / "companion"
FRAMES = ASSETS / "frames"


def png_info(path: Path) -> tuple[int, int, int]:
    data = path.read_bytes()[:26]
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"not a PNG: {path.name}")
    width, height = struct.unpack(">II", data[16:24])
    color_type = data[25]
    return width, height, color_type


class CompanionUIContractTests(unittest.TestCase):
    def test_companion_is_present_and_user_controllable(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="studio-companion"', html)
        self.assertIn('id="companion-react"', html)
        self.assertIn('id="companion-hide"', html)
        self.assertIn('id="companion-frame"', html)
        self.assertIn('id="set-companion-enabled"', html)
        self.assertIn('data-tab="companion"', html)
        self.assertIn('data-page="companion"', html)
        for control in ("set-companion-scale", "set-companion-dock", "set-companion-side-offset", "set-companion-bottom-offset", "set-companion-opacity", "set-companion-animation-speed", "set-companion-ambient", "set-companion-click-reactions", "set-companion-state-reactions"):
            self.assertIn(f'id="{control}"', html)

    def test_runtime_uses_whole_character_frames_not_articulated_parts(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
        self.assertNotIn("companion-rig", html)
        self.assertNotIn("companion-l-upper", html)
        self.assertNotIn("companion-tail-group", html)
        self.assertNotIn("transform-origin:246px 514px", css)
        self.assertIn("Every visible motion is baked into complete 320x490", css)
        self.assertIn("transform:none!important", css)

    def test_reference_frames_are_packaged_with_identical_geometry(self):
        manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
        referenced = {
            frame
            for animation in manifest["animations"].values()
            for frame in animation["frames"]
        }
        self.assertGreaterEqual(len(referenced), 50)
        missing = sorted(frame for frame in referenced if not (ASSETS / frame).is_file())
        self.assertEqual(missing, [])
        infos = {png_info(ASSETS / frame) for frame in referenced}
        self.assertEqual(infos, {(320, 490, 6)})

    def test_manifest_locks_frame_by_frame_mode_and_reference_source(self):
        manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["mode"], "frame_by_frame")
        self.assertEqual(manifest["frame_size"], [320, 490])
        self.assertEqual(manifest["render_size"], [128, 196])
        self.assertEqual(
            manifest["source_sha256"],
            "7d27c34006e7afe07adb58cb30a0ad96b5219bfe3de7834e3a401308e0af2e6e",
        )
        for key in ("neutral", "blink", "thinking", "curious", "generating", "listening", "speaking", "happy", "heart", "wink", "error", "bashful", "sleepy"):
            self.assertIn(key, manifest["animations"])
            anim = manifest["animations"][key]
            self.assertEqual(len(anim["frames"]), len(anim["durations_ms"]))

    def test_javascript_preloads_and_swaps_complete_frames(self):
        js = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("COMPANION_ANIMATIONS", js)
        self.assertIn("preloadCompanionFrames", js)
        self.assertIn("setCompanionAnimation", js)
        self.assertIn("renderCompanionFrame", js)
        self.assertIn("/static/assets/companion/frames/", js)
        self.assertNotIn("COMPANION_HEADS", js)
        self.assertNotIn("COMPANION_TAILS", js)
        self.assertIn("scheduleCompanionAmbient", js)
        self.assertIn("loopStart:3", js)

    def test_companion_is_smaller_and_anchored_to_window_bottom(self):
        css = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
        self.assertIn("position:fixed;right:var(--companion-side-offset,6px);bottom:var(--companion-bottom-offset,0px);width:var(--companion-width,128px);height:var(--companion-height,196px)", css)
        self.assertIn(".companion-frame{\n  display:block;width:100%;height:100%", css)

    def test_lively_frame_manifest_has_ambient_reactions_and_thinking_hold_loop(self):
        manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], 3)
        self.assertEqual(manifest["animations"]["thinking"]["loop_start"], 3)
        self.assertTrue(manifest["ambient"]["enabled_when_neutral"])
        self.assertEqual(manifest["ambient"]["delay_ms"], [11000, 20000])

    def test_old_articulated_assets_are_not_packaged(self):
        obsolete = {
            "torso_core.png", "pelvis_core.png", "tail_default.png", "tail_wag.png",
            "l_arm_upper.png", "l_arm_lower.png", "l_hand.png",
            "r_arm_upper.png", "r_arm_lower.png", "r_hand.png",
            "l_thigh.png", "l_calf.png", "l_foot.png",
            "r_thigh.png", "r_calf.png", "r_foot.png",
        }
        present = sorted(name for name in obsolete if (ASSETS / name).exists())
        self.assertEqual(present, [])

    def test_companion_setting_defaults_on_and_can_be_disabled(self):
        self.assertTrue(storage.DEFAULT_SETTINGS["companion_enabled"])
        self.assertFalse(storage._coerce_settings({"companion_enabled": False})["companion_enabled"])
        self.assertEqual(storage._coerce_settings({})["settings_schema"], 18)

    def test_companion_settings_are_bounded_and_reset_independently(self):
        coerced = storage._coerce_settings({
            "companion_scale": 99,
            "companion_dock": "left",
            "companion_side_offset": 999,
            "companion_bottom_offset": -20,
            "companion_opacity": 0.01,
            "companion_animation_speed": 9,
            "companion_ambient_mode": "lively",
            "companion_click_reactions": False,
            "companion_state_reactions": False,
        })
        self.assertEqual(coerced["companion_scale"], 1.60)
        self.assertEqual(coerced["companion_dock"], "left")
        self.assertEqual(coerced["companion_side_offset"], 160)
        self.assertEqual(coerced["companion_bottom_offset"], 0)
        self.assertEqual(coerced["companion_opacity"], 0.35)
        self.assertEqual(coerced["companion_animation_speed"], 1.75)
        self.assertEqual(coerced["companion_ambient_mode"], "lively")
        self.assertFalse(coerced["companion_click_reactions"])
        self.assertFalse(coerced["companion_state_reactions"])

    def test_javascript_applies_companion_presentation_and_speed(self):
        js = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function applyCompanionPresentation", js)
        self.assertIn("companion_animation_speed", js)
        self.assertIn("companion_ambient_mode", js)
        self.assertIn("companion_state_reactions === false", js)
        self.assertIn("companion_click_reactions === false", js)


if __name__ == "__main__":
    unittest.main()
