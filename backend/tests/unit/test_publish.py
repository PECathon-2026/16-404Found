import base64

from app.services.publish import _scrub, auth_env, branch_name


def test_token_goes_via_env_header_not_argv_or_url():
    env = auth_env("ghp_SECRETTOKEN123")
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    val = env["GIT_CONFIG_VALUE_0"]
    assert val.startswith("AUTHORIZATION: basic ") and "ghp_SECRETTOKEN123" not in val
    assert base64.b64decode(val.split()[-1]).decode() == "x-access-token:ghp_SECRETTOKEN123"
    assert auth_env(None) == {}


def test_error_messages_are_scrubbed():
    assert "SECRET" not in _scrub("fatal: could not read from https://x:SECRET@github.com", "SECRET")


def test_branch_names_are_safe_and_namespaced():
    b = branch_name("mis_01ABCDEFGHJKMNPQRSTVWXYZ12", "Fix `rm -rf /` & more!!")
    assert b.startswith("devpilot/") and " " not in b and ".." not in b and "`" not in b and b.endswith("xyz12")
