import unicodedata
from difflib import SequenceMatcher

from app.adapters.kakao import KakaoPlace

from .geo import distance_m
from .repository import PublicPlaceRepository
from .schemas import PublicPlace
from .settings import PlaceMatchSettings


def normalize_name(name: str) -> str:
    """비교용 이름. 전각·반각을 맞추고 소문자로 바꾼 뒤 글자와 숫자만 남긴다."""
    folded = unicodedata.normalize("NFKC", name).casefold()
    return "".join(char for char in folded if char.isalnum())


def name_similarity(left: str, right: str) -> float:
    """두 장소 이름의 유사도(0~1). 띄어쓰기와 기호 차이는 무시한다."""
    a, b = normalize_name(left), normalize_name(right)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def is_partial_name(left: str, right: str) -> bool:
    """한쪽 이름이 다른 쪽에 통째로 들어 있지만 같지는 않은 경우.

    '예시해수욕장' 과 '예시해수욕장 주차장' 처럼 부속 시설이거나 줄여 부른 이름이다. 글자 유사도는 높게
    나오지만 다른 장소일 수 있으므로 자동으로 잇지 않는다. 같은 장소라면 수동 매칭표에 등록한다.
    """
    a, b = normalize_name(left), normalize_name(right)
    return a != b and bool(a) and bool(b) and (a in b or b in a)


class PlaceMatcher:
    """카카오 장소가 공공 DB 의 어느 장소인지 찾는다(FR-001).

    1. 수동 매칭표(카카오 장소 ID 기준)에 있으면 그 장소다.
    2. 없으면 반경 안에서 이름 유사도가 기준 이상인 장소 중 가장 비슷한 것. 유사도가 같으면 가까운 쪽이다.
       한쪽 이름이 다른 쪽에 포함되기만 하는 경우는 잇지 않는다(`is_partial_name`).

    잘못 이어서 다른 장소의 영업시간을 보여 주는 것보다 '기본 정보만'으로 두는 쪽을 택한다(NFR-012).
    """

    def __init__(self, repository: PublicPlaceRepository, settings: PlaceMatchSettings) -> None:
        self._repository = repository
        self._settings = settings

    def match(self, place: KakaoPlace) -> PublicPlace | None:
        override = self._repository.find_by_kakao_id(place.kakao_place_id)
        if override is not None:
            return override

        radius = self._settings.match_radius_m
        best: tuple[float, float, str, PublicPlace] | None = None
        for candidate in self._repository.find_near(place.lat, place.lng, radius):
            # 저장소 구현이 반경을 넓게 잡아도 기준을 지키도록 다시 확인한다.
            distance = distance_m(place.lat, place.lng, candidate.lat, candidate.lng)
            similarity = name_similarity(place.name, candidate.name)
            if distance > radius or similarity < self._settings.name_similarity_threshold:
                continue
            if is_partial_name(place.name, candidate.name):
                continue
            # 유사도가 높은 쪽, 같으면 가까운 쪽. 그래도 같으면 조회 순서와 무관하도록 ID 로 정한다.
            rank = (similarity, -distance, candidate.id)
            if best is None or rank > best[:3]:
                best = (*rank, candidate)
        return best[3] if best else None
