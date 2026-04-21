from app.services.process_service import _condition_matches, _resolve_next_nodes


def test_condition_matches_variable_expression() -> None:
    assert _condition_matches("var:risk_level=='high'", {"variables": {"risk_level": "high"}})
    assert not _condition_matches("var:risk_level=='low'", {"variables": {"risk_level": "high"}})


def test_resolve_next_nodes_with_branch_rule() -> None:
    definition = {
        "transitions": {
            "review": {
                "branches": [
                    {"when": "var:risk_level=='high'", "next": ["senior_review", "audit_check"]},
                    {"when": "always", "next": ["approve"]},
                ]
            }
        }
    }
    nodes = _resolve_next_nodes(definition, "review", "approve", {"risk_level": "high"})
    assert nodes == ["senior_review", "audit_check"]
