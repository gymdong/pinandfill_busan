from pydantic import SecretStr


def blank_key_is_no_key(value: object) -> object:
    """외부 API 키 설정의 공통 규칙(`mode="before"` 검증기에서 쓴다).

    빈 값·공백만 있는 값은 키가 없는 것(None)으로 보고, 그 외에는 앞뒤 공백을 뗀 값을 쓴다.
    값은 오류나 로그에 싣지 않는다.
    """
    secret = value.get_secret_value() if isinstance(value, SecretStr) else value
    if not isinstance(secret, str):
        return value
    return secret.strip() or None
