import type { BlockPlace, Coords, SessionCoords } from '@/types/api';

/**
 * 카카오 장소의 이름·좌표를 이번 접속 동안만 보관한다(D6, 카카오 공식 답변).
 * 모듈 메모리라 새로고침하거나 탭을 닫으면 사라진다. localStorage·sessionStorage·서버로 옮기지 않는다.
 * 값이 바뀌어도 화면이 다시 그려지지는 않으므로, 블록을 추가하기 전에 먼저 기억해 둔다.
 */
export interface KakaoSessionPlace {
  name: string;
  coords: Coords;
}

const places = new Map<string, KakaoSessionPlace>();

export function rememberKakaoPlace(kakaoPlaceId: string, place: KakaoSessionPlace): void {
  places.set(kakaoPlaceId, place);
}

export function getKakaoPlace(kakaoPlaceId: string): KakaoSessionPlace | null {
  return places.get(kakaoPlaceId) ?? null;
}

/** 일정 계산 요청에 붙일 좌표. 이름은 서버에 보내지 않는다. 기억한 장소가 없으면 undefined */
export function getSessionCoords(): SessionCoords | undefined {
  if (places.size === 0) return undefined;
  return Object.fromEntries([...places].map(([id, place]) => [id, place.coords]));
}

export function clearKakaoSession(): void {
  places.clear();
}

/**
 * 블록 장소의 표시용 이름·좌표. 카카오 장소를 이번 접속에서 고르지 않았으면 null이며,
 * 화면은 '다시 선택 필요'와 카카오맵 링크(외부 브라우저)를 보여 준다.
 */
export function resolveBlockPlace(place: BlockPlace): KakaoSessionPlace | null {
  if (place.source === 'PUBLIC') return { name: place.name, coords: { lat: place.lat, lng: place.lng } };
  return getKakaoPlace(place.kakaoPlaceId);
}
