import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from engine import agents
from server import app


ROOT = Path(__file__).resolve().parents[1]


class CustomSpecialistRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.custom_path = Path(self.tmp.name) / "custom_specialists.json"
        self.path_patch = patch.object(agents, "CUSTOM_REGISTRY_PATH", self.custom_path)
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.tmp.cleanup()

    def payload(self, **overrides):
        base = {
            "template_id": "general-expert",
            "name": "Systems Cartographer",
            "description": "Maps complex systems and their dependencies.",
            "group": "AI & Computing",
            "mission": "map complex systems, dependencies, and failure boundaries",
            "tone": "calm, exact, and concise",
            "approach": "Separate confirmed facts from assumptions and trace dependencies before proposing changes.",
            "structure": "Organize findings by system boundary, dependency, risk, and action.",
            "output": "Produce implementation-ready maps, checks, and recommendations.",
            "advanced_directive": "Do not invent missing topology.",
        }
        base.update(overrides)
        return base

    def test_create_custom_specialist_persists_fields_and_compiled_directive(self):
        created = agents.create_custom_agent(self.payload())
        self.assertTrue(created["id"].startswith("custom-systems-cartographer"))
        self.assertTrue(created["custom"])
        self.assertEqual(created["template_id"], "general-expert")
        self.assertIn("You are Systems Cartographer", created["prompt"])
        self.assertIn("Operating Rules:", created["prompt"])
        self.assertIn("1. Tone: calm, exact, and concise", created["prompt"])
        self.assertIn("2. Approach:", created["prompt"])
        self.assertIn("3. Structure:", created["prompt"])
        self.assertIn("4. Output:", created["prompt"])
        self.assertIn("Additional Directives:", created["prompt"])
        saved = json.loads(self.custom_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["version"], 1)
        self.assertEqual(len(saved["agents"]), 1)

    def test_custom_agents_merge_into_assigned_group_and_my_specialists(self):
        baseline = agents.registry_count()
        first = agents.create_custom_agent(self.payload())
        second = agents.create_custom_agent(self.payload(name="Threat Cartographer", group="Security"))
        self.assertEqual(agents.registry_count(), baseline + 2)
        my_agents = agents.list_agents(group=agents.CUSTOM_GROUP_NAME, limit=500)
        self.assertEqual({x["id"] for x in my_agents}, {first["id"], second["id"]})
        ai_ids = {x["id"] for x in agents.list_agents(group="AI & Computing", limit=1000)}
        security_ids = {x["id"] for x in agents.list_agents(group="Security", limit=1000)}
        self.assertIn(first["id"], ai_ids)
        self.assertIn(second["id"], security_ids)
        groups = {g["id"]: g["count"] for g in agents.list_groups()}
        self.assertEqual(groups[agents.CUSTOM_GROUP_NAME], 2)

    def test_update_keeps_stable_id_and_recompiles_prompt(self):
        created = agents.create_custom_agent(self.payload())
        updated = agents.update_custom_agent(created["id"], self.payload(name="System Mapper", tone="brief and surgical"))
        self.assertEqual(updated["id"], created["id"])
        self.assertEqual(updated["name"], "System Mapper")
        self.assertIn("1. Tone: brief and surgical", agents.prompt_for(created["id"]))

    def test_duplicate_gets_unique_stable_id(self):
        created = agents.create_custom_agent(self.payload())
        duplicate = agents.duplicate_custom_agent(created["id"])
        self.assertNotEqual(duplicate["id"], created["id"])
        self.assertTrue(duplicate["custom"])
        self.assertIn("Copy", duplicate["name"])

    def test_delete_custom_specialist_cannot_delete_builtin(self):
        created = agents.create_custom_agent(self.payload())
        self.assertTrue(agents.delete_custom_agent(created["id"]))
        self.assertIsNone(agents.get_agent(created["id"]))
        builtin = agents.list_agents(limit=1)[0]
        with self.assertRaises(ValueError):
            agents.delete_custom_agent(builtin["id"])

    def test_invalid_group_and_oversized_prompt_are_rejected(self):
        with self.assertRaises(ValueError):
            agents.create_custom_agent(self.payload(group="Made Up Group"))
        with self.assertRaises(ValueError):
            agents.create_custom_agent(self.payload(advanced_directive="x" * 8000))

    def test_templates_are_data_driven_and_cover_requested_presets(self):
        templates = agents.list_templates()
        ids = {item["id"] for item in templates}
        self.assertTrue({
            "blank", "general-expert", "coding-engineering", "research-analysis",
            "creative-design", "security", "business-strategy",
        }.issubset(ids))
        self.assertTrue((ROOT / "engine" / "agent_templates.json").is_file())


class CustomSpecialistAPIAndUIContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.custom_path = Path(self.tmp.name) / "custom_specialists.json"
        self.path_patch = patch.object(agents, "CUSTOM_REGISTRY_PATH", self.custom_path)
        self.path_patch.start()
        self.client = TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50124))

    def tearDown(self):
        self.path_patch.stop()
        self.tmp.cleanup()

    def test_crud_api_round_trip(self):
        templates = self.client.get("/api/specialists/templates")
        self.assertEqual(templates.status_code, 200)
        self.assertGreaterEqual(len(templates.json()["templates"]), 7)

        payload = CustomSpecialistRegistryTests.payload(self)
        created_res = self.client.post("/api/specialists/custom", json=payload)
        self.assertEqual(created_res.status_code, 200)
        created = created_res.json()["agent"]

        detail_res = self.client.get(f"/api/specialists/custom/{created['id']}")
        self.assertEqual(detail_res.status_code, 200)
        self.assertEqual(detail_res.json()["agent"]["name"], payload["name"])

        payload["tone"] = "terse and technical"
        update_res = self.client.put(f"/api/specialists/custom/{created['id']}", json=payload)
        self.assertEqual(update_res.status_code, 200)
        self.assertIn("terse and technical", update_res.json()["agent"]["prompt"])

        duplicate_res = self.client.post(f"/api/specialists/custom/{created['id']}/duplicate")
        self.assertEqual(duplicate_res.status_code, 200)
        self.assertNotEqual(duplicate_res.json()["agent"]["id"], created["id"])

        delete_res = self.client.delete(f"/api/specialists/custom/{created['id']}")
        self.assertEqual(delete_res.status_code, 200)
        self.assertTrue(delete_res.json()["ok"])

    def test_specialist_dialog_exposes_builder_and_live_preview_controls(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
        for control in (
            "create-specialist", "specialist-builder", "specialist-template", "specialist-name",
            "specialist-description", "specialist-group-field", "specialist-mission", "specialist-tone",
            "specialist-approach", "specialist-structure", "specialist-output", "specialist-advanced",
            "specialist-directive-preview", "save-specialist", "duplicate-specialist", "delete-specialist",
        ):
            self.assertIn(f'id="{control}"', html)
        for fn in (
            "openSpecialistBuilder", "refreshSpecialistDirectivePreview", "saveCustomSpecialist",
            "duplicateCustomSpecialist", "deleteCustomSpecialist",
        ):
            self.assertIn(f"function {fn}", js)
        self.assertIn("/api/specialists/templates", js)
        self.assertIn("/api/specialists/custom", js)
        self.assertIn(".specialist-builder", css)


if __name__ == "__main__":
    unittest.main()
