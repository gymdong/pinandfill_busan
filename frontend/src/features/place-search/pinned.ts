import type { BadgeKind } from '@/components';
import type { PinnedPlace } from '@/store/tripDraft';
import type { PlaceSearchItem } from '@/types/api';

/**
 * 검색 결과를 '꼭 갈 곳'에 담을 형태로 바꾼다.
 * 공공 DB와 매칭된 장소는 places.id로, 매칭되지 않은 장소는 카카오 장소 키로 담는다(D6).
 */
export function toPinnedPlace(item: PlaceSearchItem): PinnedPlace {
  return item.placeId
    ? { kind: 'PUBLIC', placeId: item.placeId, name: item.name, coords: item.coords }
    : { kind: 'KAKAO', kakaoPlaceId: item.kakaoPlaceId, placeUrl: item.placeUrl, name: item.name, coords: item.coords };
}

/** 담은 장소의 매칭 배지. 공공 DB 장소는 '상세 정보 있음', 카카오 장소는 '기본 정보만'(FR-001) */
export function pinnedBadgeKind(place: PinnedPlace): BadgeKind {
  return place.kind === 'PUBLIC' ? 'detail' : 'basic';
}
