"""로그 설정(NFR-010: 키·비밀 URL 을 로그에 남기지 않는다)."""

import logging


def quiet_http_client_logs() -> None:
    """httpx·httpcore 는 INFO·DEBUG 로 요청 URL 전체를 남긴다. TourAPI serviceKey(쿼리)·웹훅 URL 이 들어가므로 올린다.

    CLI·앱 시작 시 부르고, 비밀 URL 로 요청하는 구성요소(TourAPI 잡·관리자 알림)도 직접 부른다. 여러 번 불러도 같다.
    """
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
