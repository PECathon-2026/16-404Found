from users import get_user, make_db


def test_get_user():
    assert get_user(make_db(), 1)["name"] == "Ana"
