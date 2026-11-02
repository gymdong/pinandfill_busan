/** 화면 경로. 링크는 문자열을 직접 쓰지 말고 이 빌더를 사용한다. */
export const paths = {
  tripStart: () => '/',
  timeline: (tripId: string) => `/trips/${tripId}`,
  mapView: (tripId: string) => `/trips/${tripId}/map`,
  placeDetail: (placeId: string, date?: string) =>
    date ? `/places/${placeId}?date=${encodeURIComponent(date)}` : `/places/${placeId}`,
  moodSearch: () => '/mood',
  admin: () => '/admin',
  photoSearch: () => '/photo',
  sharedTrip: (token: string) => `/shared/${token}`,
} as const;
