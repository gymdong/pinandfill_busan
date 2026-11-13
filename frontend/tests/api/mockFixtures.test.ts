import { describe, expect, it } from 'vitest';
import { mockKakaoKey, searchItems } from '@/api/mock/fixtures/places';
import { schedule } from '@/api/mock/fixtures/schedule';

describe('mock 카카오 장소 키', () => {
  const blockKeys = schedule.days
    .flatMap((day) => day.blocks)
    .flatMap((block) => (block.place.source === 'KAKAO' ? [block.place] : []));

  it.each([...searchItems, ...blockKeys, mockKakaoKey(42)])('백엔드가 받는 형식이다: $kakaoPlaceId', (key) => {
    expect(key.kakaoPlaceId).toMatch(/^[0-9]+$/);
    expect(key.placeUrl).toBe(`https://place.map.kakao.com/${key.kakaoPlaceId}`);
  });

  it('일정의 카카오 블록은 검색 결과의 미매칭 장소와 같은 키를 쓴다', () => {
    const unmatched = searchItems.find((item) => item.placeId === null);
    expect(blockKeys.map((key) => key.kakaoPlaceId)).toContain(unmatched?.kakaoPlaceId);
  });
});
