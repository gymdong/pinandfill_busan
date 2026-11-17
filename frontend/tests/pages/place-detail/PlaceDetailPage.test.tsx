import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, placesApi } from '@/api';
import { PLACE_IDS, placeSummaries, sparseDetail, taejongdaeDetail } from '@/api/mock/fixtures/places';
import { dayTypeOf, describeHours } from '@/features/place-detail/hours';
import PlaceDetailPage from '@/pages/place-detail';
import { useTripDraft } from '@/store/tripDraft';
import type { PlaceDetailResponse } from '@/types/api';

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/places/:placeId" element={<PlaceDetailPage />} />
        <Route path="/" element={<p>여행 시작 화면</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

function mockDetail(detail: PlaceDetailResponse) {
  return vi.spyOn(placesApi, 'get').mockResolvedValue(detail);
}

const PATH = `/places/${PLACE_IDS.taejongdae}`;

describe('UI-04 장소 상세', () => {
  beforeEach(() => useTripDraft.getState().reset());

  it('장소 ID와 날짜로 상세를 불러와 이름·분류·그날 영업시간을 보여 준다', async () => {
    const get = mockDetail(taejongdaeDetail);
    renderAt(`${PATH}?date=2026-10-17`);

    expect(await screen.findByRole('heading', { name: '태종대' })).toBeInTheDocument();
    expect(get.mock.calls[0]!.slice(0, 2)).toEqual([PLACE_IDS.taejongdae, '2026-10-17']);
    expect(screen.getByText('자연 명소 · 야외')).toBeInTheDocument();
    const info = screen.getByRole('region', { name: '운영 정보' });
    expect(within(info).getByText('10월 17일 (토)')).toBeInTheDocument();
    expect(within(info).getAllByText('09:00 – 18:00').length).toBeGreaterThan(0);
    expect(within(info).getByText('예상 붐빔')).toBeInTheDocument();
  });

  it('날짜가 없으면 요일별 운영시간을 안내한다', async () => {
    mockDetail(taejongdaeDetail);
    renderAt(PATH);
    await screen.findByRole('heading', { name: '태종대' });
    expect(screen.getByText('요일별 시간을 확인하세요')).toBeInTheDocument();
    expect(screen.getByText('요일별 운영시간')).toBeInTheDocument();
  });

  it('그날이 휴무이면 휴무를 알리고, 휴무 안내 문구가 있으면 함께 보여 준다', async () => {
    mockDetail({
      ...taejongdaeDetail,
      place: { ...taejongdaeDetail.place, closedDaysText: '매주 월요일' },
      hours: taejongdaeDetail.hours.map((item) => (item.dayType === 'MON' ? { ...item, isClosed: true } : item)),
    });
    renderAt(`${PATH}?date=2026-10-19`);
    expect(await screen.findByText('이 날은 휴무예요')).toBeInTheDocument();
    expect(screen.getByText('매주 월요일')).toBeInTheDocument();
  });

  it('영업시간·사진·혼잡 근거가 없으면 값을 만들지 않고 확인 필요·사진 없음·정보 부족으로 표시한다(NFR-012)', async () => {
    mockDetail(sparseDetail(placeSummaries.millakPark));
    renderAt(`/places/${PLACE_IDS.millakPark}?date=2026-10-17`);

    await screen.findByRole('heading', { name: '민락수변공원' });
    expect(screen.getByText('영업시간 확인 필요')).toBeInTheDocument();
    expect(screen.getByText('사진 없음')).toBeInTheDocument();
    expect(screen.getByText('정보 부족')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.queryByText('요일별 운영시간')).not.toBeInTheDocument();
  });

  it('사진마다 출처와 저작권 유형을 표시하고 대표 사진부터 넘겨 본다(FR-014, AC-014)', async () => {
    const [primary, second] = taejongdaeDetail.photos;
    mockDetail({
      ...taejongdaeDetail,
      // 대표 사진이 뒤에 와도 먼저 보여 준다. 두 번째 사진은 저작권 유형이 없다.
      photos: [{ ...second!, sourceOrg: '부산광역시', licenseType: null }, primary!],
    });
    renderAt(PATH);

    const image = await screen.findByRole('img', { name: '태종대 사진 1' });
    expect(image).toHaveAttribute('src', primary!.url);
    expect(screen.getByText('사진 한국관광공사 · 공공누리 제1유형')).toBeInTheDocument();
    expect(screen.getByText('1 / 2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '이전 사진' })).toBeDisabled();

    await userEvent.click(screen.getByRole('button', { name: '다음 사진' }));
    expect(screen.getByRole('img', { name: '태종대 사진 2' })).toHaveAttribute('src', second!.url);
    expect(screen.getByText('사진 부산광역시 · 저작권 유형 확인 필요')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '다음 사진' })).toBeDisabled();
  });

  it('장소 정보의 출처와 기준일, 혼잡 근거를 표시한다(NFR-007)', async () => {
    mockDetail(taejongdaeDetail);
    renderAt(PATH);
    const sources = await screen.findByRole('contentinfo', { name: '출처' });
    expect(sources).toHaveTextContent('장소 정보 한국관광공사 · 10월 13일 (화) 기준');
    expect(sources).toHaveTextContent('혼잡 근거 행정동 생활인구, 도시철도 승하차');
  });

  it('꼭 갈 곳에 담고 다시 뺄 수 있다', async () => {
    mockDetail(taejongdaeDetail);
    renderAt(PATH);
    await userEvent.click(await screen.findByRole('button', { name: '꼭 갈 곳에 담기' }));
    expect(useTripDraft.getState().pinned).toEqual([
      { kind: 'PUBLIC', placeId: PLACE_IDS.taejongdae, name: '태종대', coords: { lat: 35.0517, lng: 129.0855 } },
    ]);
    await userEvent.click(screen.getByRole('button', { name: /담김 · 빼기/ }));
    expect(useTripDraft.getState().pinned).toEqual([]);
  });

  it('없는 장소(ERR-016)는 다시 시도 대신 처음으로 돌아가게 한다', async () => {
    vi.spyOn(placesApi, 'get').mockRejectedValue(new ApiError({ id: 'ERR-016', status: 404 }));
    renderAt('/places/unknown');
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '다시 시도' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '처음으로' }));
    expect(screen.getByText('여행 시작 화면')).toBeInTheDocument();
  });

  it('일시적인 오류는 다시 시도할 수 있다', async () => {
    const get = vi
      .spyOn(placesApi, 'get')
      .mockRejectedValueOnce(new ApiError({ id: 'ERR-017', status: 503 }))
      .mockResolvedValue(taejongdaeDetail);
    renderAt(PATH);
    await userEvent.click(await screen.findByRole('button', { name: '다시 시도' }));
    expect(await screen.findByRole('heading', { name: '태종대' })).toBeInTheDocument();
    expect(get).toHaveBeenCalledTimes(2);
  });
});

describe('영업시간 표시', () => {
  it('날짜에서 요일을 구하고 형식이 다르면 구하지 않는다', () => {
    expect(dayTypeOf('2026-10-17')).toBe('SAT');
    expect(dayTypeOf('2026-10-19')).toBe('MON');
    expect(dayTypeOf('10/17')).toBeNull();
    expect(dayTypeOf(null)).toBeNull();
  });

  it('달력에 없는 날짜는 다른 날로 넘겨 읽지 않고, 윤년 2월 29일은 받는다', () => {
    expect(dayTypeOf('2026-02-30')).toBeNull();
    expect(dayTypeOf('2026-02-29')).toBeNull();
    expect(dayTypeOf('2026-13-01')).toBeNull();
    expect(dayTypeOf('2024-02-29')).toBe('THU');
  });

  it('공휴일 영업시간은 요일별 표에만 보이고 그날 영업시간에는 쓰지 않는다', async () => {
    const holiday = { ...taejongdaeDetail.hours[0]!, dayType: 'HOLIDAY' as const, openTime: '10:00', closeTime: '16:00' };
    mockDetail({ ...taejongdaeDetail, hours: [...taejongdaeDetail.hours, holiday] });
    renderAt(`${PATH}?date=2026-10-17`);
    const info = await screen.findByRole('region', { name: '운영 정보' });
    expect(within(info).getByText('공휴일')).toBeInTheDocument();
    expect(within(info).getAllByText('10:00 – 16:00')).toHaveLength(1);
    // 그날(토요일) 줄과 요일별 표의 토요일 줄은 요일 기준 시간이다.
    expect(within(info).getAllByText('09:00 – 18:00').length).toBeGreaterThanOrEqual(2);
  });

  it('주소의 날짜가 달력에 없으면 그날 영업시간 대신 요일별 안내를 보여 준다', async () => {
    mockDetail(taejongdaeDetail);
    renderAt(`${PATH}?date=2026-02-30`);
    await screen.findByRole('heading', { name: '태종대' });
    expect(screen.getByText('요일별 시간을 확인하세요')).toBeInTheDocument();
  });

  it('휴게시간을 함께 적고, 시각이 비면 확인 필요로 둔다', () => {
    const base = { dayType: 'MON' as const, openTime: '09:00', closeTime: '18:00', breakStart: null, breakEnd: null, isClosed: false };
    expect(describeHours({ ...base, breakStart: '12:00', breakEnd: '13:00' })).toEqual({
      kind: 'open',
      text: '09:00 – 18:00 (휴게 12:00 – 13:00)',
    });
    expect(describeHours({ ...base, closeTime: null }).kind).toBe('unknown');
    expect(describeHours({ ...base, isClosed: true }).kind).toBe('closed');
    expect(describeHours(undefined).kind).toBe('unknown');
  });
});
