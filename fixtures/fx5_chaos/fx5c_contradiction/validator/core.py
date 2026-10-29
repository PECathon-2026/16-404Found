"""Token validator implementation."""


def validate_token(token: str) -> bool:
    if not token or len(token) < 4:
        return False
    return token.isalnum()
