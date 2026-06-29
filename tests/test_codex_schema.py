from __future__ import annotations

import unittest
import json
from typing import Any

from medical_deep_research.runtime import AgentResearchOutput, _strict_json_schema_for_model


def _walk_schema(node: Any) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            objects.extend(_walk_schema(item))
        return objects
    if not isinstance(node, dict):
        return objects

    if node.get("type") == "object" or isinstance(node.get("properties"), dict):
        objects.append(node)
    for value in node.values():
        objects.extend(_walk_schema(value))
    return objects


class CodexSchemaTests(unittest.TestCase):
    def test_codex_output_schema_is_strict_for_openai_response_format(self) -> None:
        schema = _strict_json_schema_for_model(AgentResearchOutput)

        self.assertNotIn("default", str(schema))
        self.assertNotIn("source_queries", json.dumps(schema))
        for object_schema in _walk_schema(schema):
            self.assertIs(object_schema.get("additionalProperties"), False)
            properties = object_schema.get("properties")
            if isinstance(properties, dict):
                self.assertEqual(object_schema.get("required"), list(properties))


if __name__ == "__main__":
    unittest.main()
