"""Tailscale's current default policy uses grants + ipsets — not errors."""
from server import acl

DEFAULT_POLICY = """// Example/default ACLs for unrestricted connections.
{
	"grants": [
		// Allow all connections.
		{"src": ["*"], "dst": ["*"], "ip": ["*"]},
	],
	"ipsets": {"ipset:office": ["add 100.25.20.0/24"]},
	"ssh": [{"action": "check", "src": ["autogroup:member"], "dst": ["autogroup:self"], "users": ["autogroup:nonroot", "root"]}],
}
"""


def test_grants_and_ipsets_are_known_sections():
    assert acl.validate(DEFAULT_POLICY) == []


def test_structured_view_lists_grants_and_ipsets():
    parsed, _ = acl.parse(DEFAULT_POLICY)
    kinds = {row["kind"] for row in acl.structured(parsed)}
    assert {"grants", "ipsets"} <= kinds


def test_unknown_section_still_flagged():
    errors = acl.validate('{"grantz": []}')
    assert errors and "grantz" in errors[0]["message"]
