import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, recommendApi } from '@/api';
import { moodAvoid, moodPlaces, moodTags, PLACE_IDS } from '@/api/mock/fixtures/places';
import MoodSearchPage from '@/pages/mood-search';
import { useTripDraft } from '@/store/tripDraft';
import type { MoodRequest, MoodResponse } from '@/types/api';

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/mood']}>
      <Routes>
        <Route path="/mood" element={<MoodSearchPage />} />
        <Route path="/" element={<p>여행 시작 화면</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

/** SD-03: 문장은 태그로만 해석하고, 태그를 보내면 맞는 장소를 돌려준다(mock 과 같은 동작). */
function mockMood(places = moodPlaces) {
  return vi.spyOn(recommendApi, 'mood').mockImplementation(async (body: MoodRequest): Promise<MoodResponse> => {
    if (body.text !== undefined) return { tags: moodTags, avoid: moodAvoid, places: [] };
    const selected = body.tags ?? [];
    return {
      tags: moodTags.filter((tag) => selected.includes(tag.code)),
      avoid: body.avoid ?? [],
      places: places.filter((item) => item.evidence.matchedTags.some((tag) => selected.includes(tag))),
    };
  });
}

async function search(text = '조용한 바다 감성, 사람 적은 골목') {
  await userEvent.type(screen.getByLabelText('원하는 분위기'), text);
  await userEvent.click(screen.getByRole('button', { name: '찾기' }));
}

describe('UI-08 분위기로 찾기', () => {
  beforeEach(() => {
    useTripDraft.getState().reset();
    useTripDraft.getState().setConditions({ dates: { start: '2026-10-17', end: '2026-10-19' } });
  });

  it('문장을 태그와 피할 조건 칩으로 해석해 보여 주고, 그 태그로 추천을 받는다(AC-015)', async () => {
    const mood = mockMood();
    renderPage();
    await search();

    const chips = await screen.findByRole('group', { name: '해석된 조건' });
    for (const label of ['바다 전망', '골목·산책', '실내 제외']) {
      expect(within(chips).getByRole('button', { name: new RegExp(label) })).toHaveAttribute('aria-pressed', 'true');
    }
    expect(await screen.findByRole('list', { name: '추천 장소' })).toBeInTheDocument();
    // 여행 시작일을 혼잡 기준일로 보낸다.
    expect(mood.mock.calls.map(([body]) => body)).toEqual([
      { text: '조용한 바다 감성, 사람 적은 골목', date: '2026-10-17' },
      { tags: ['SEA_VIEW', 'ALLEY_WALK'], avoid: ['실내 제외'], date: '2026-10-17' },
    ]);
    expect(screen.getByText(/10월 17일 \(토\) 기준/)).toBeInTheDocument();
  });

  it('추천마다 맞은 태그와 근거 문장, 사진 출처·저작권 유형, 예상 혼잡을 보여 준다(FR-014)', async () => {
    mockMood();
    renderPage();
    await search();

    const [first, , third] = within(await screen.findByRole('list', { name: '추천 장소' })).getAllByRole('listitem');
    expect(within(first!).getByRole('heading', { name: '흰여울문화마을' })).toBeInTheDocument();
    expect(within(first!).getByText('바다 전망 · 골목·산책 — “해안 절벽 위로 이어진 좁은 골목”')).toBeInTheDocument();
    // 근거 문장의 출처 기관·기준일을 함께 보여 준다(NFR-007). 출처가 없으면 지어내지 않는다.
    expect(within(first!).getByText(/^설명 출처 한국관광공사 · /)).toBeInTheDocument();
    expect(within(third!).queryByText(/설명 출처/)).not.toBeInTheDocument();
    expect(within(first!).getByText('한국관광공사 · 공공누리 제1유형')).toBeInTheDocument();
    expect(within(first!).getByText('예상 여유')).toBeInTheDocument();
    // 사진이 없으면 다른 사진을 끌어오지 않고 '사진 없음'으로 둔다.
    expect(within(third!).getByText('사진 없음')).toBeInTheDocument();
    expect(within(third!).queryByRole('img')).not.toBeInTheDocument();
  });

  it('태그 칩을 끄면 남은 태그로 다시 추천받고, 모두 끄면 태그를 고르라고 안내한다', async () => {
    const mood = mockMood();
    renderPage();
    await search();
    await screen.findByRole('heading', { name: '청사포' });

    await userEvent.click(screen.getByRole('button', { name: /바다 전망/ }));
    await waitFor(() => expect(screen.queryByRole('heading', { name: '청사포' })).not.toBeInTheDocument());
    expect(screen.getByRole('heading', { name: '초량 이바구길' })).toBeInTheDocument();
    expect(mood.mock.calls.at(-1)![0]).toEqual({ tags: ['ALLEY_WALK'], avoid: ['실내 제외'], date: '2026-10-17' });

    await userEvent.click(screen.getByRole('button', { name: /골목·산책/ }));
    expect(await screen.findByText('태그를 하나 이상 골라 주세요.')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: '추천 장소' })).not.toBeInTheDocument();
  });

  it('피할 조건 칩을 끄면 그 조건을 빼고 다시 추천받는다', async () => {
    const mood = mockMood();
    renderPage();
    await search();
    await screen.findByRole('list', { name: '추천 장소' });
    await userEvent.click(screen.getByRole('button', { name: /실내 제외/ }));
    await waitFor(() => expect(mood.mock.calls.at(-1)![0]).toMatchObject({ avoid: [] }));
  });

  it('추천을 담으면 꼭 갈 곳에 들어가고, 담은 수와 함께 돌아간다', async () => {
    mockMood();
    renderPage();
    await search();
    await userEvent.click(await screen.findByRole('button', { name: '흰여울문화마을 담기' }));
    await userEvent.click(screen.getByRole('button', { name: '청사포 담기' }));
    await userEvent.click(screen.getByRole('button', { name: '청사포 빼기' }));

    expect(useTripDraft.getState().pinned).toEqual([
      { kind: 'PUBLIC', placeId: PLACE_IDS.huinnyeoul, name: '흰여울문화마을', coords: { lat: 35.0784, lng: 129.0453 } },
    ]);
    expect(screen.getByRole('button', { name: '흰여울문화마을 빼기' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: '1곳 담고 돌아가기' }));
    expect(screen.getByText('여행 시작 화면')).toBeInTheDocument();
  });

  it('해석된 태그가 없으면 다른 표현을 안내하고 추천을 요청하지 않는다', async () => {
    const mood = vi.spyOn(recommendApi, 'mood').mockResolvedValue({ tags: [], avoid: [], places: [] });
    renderPage();
    await search('아무 말');
    expect(await screen.findByRole('alert')).toHaveTextContent('문장에서 분위기를 읽지 못했어요');
    expect(mood).toHaveBeenCalledTimes(1);
  });

  it('추천 결과가 0개면 지금 할 수 있는 동작(태그 끄기·다시 적기)을 안내한다(FR-015)', async () => {
    mockMood([]);
    renderPage();
    await search();
    expect(await screen.findByRole('alert')).toHaveTextContent('어울리는 곳을 찾지 못했어요. 태그를 몇 개 꺼 보거나 다른 표현으로 다시 적어 주세요.');
  });

  it('새 문장을 해석하는 동안 이전 칩·추천을 숨겨 이전 태그로 추천받지 않는다', async () => {
    const mood = mockMood();
    renderPage();
    await search('바다');
    await screen.findByRole('list', { name: '추천 장소' });

    // 두 번째 해석은 응답을 붙잡아 둔다.
    let release: (value: MoodResponse) => void = () => {};
    mood.mockImplementationOnce(() => new Promise<MoodResponse>((resolve) => { release = resolve; }));
    await userEvent.clear(screen.getByLabelText('원하는 분위기'));
    await search('골목');

    expect(screen.queryByRole('group', { name: '해석된 조건' })).not.toBeInTheDocument();
    expect(screen.queryByRole('list', { name: '추천 장소' })).not.toBeInTheDocument();
    expect(screen.getByText('문장을 해석하는 중이에요')).toBeInTheDocument();

    release({ tags: moodTags.filter((tag) => tag.code === 'ALLEY_WALK'), avoid: [], places: [] });
    const chips = await screen.findByRole('group', { name: '해석된 조건' });
    expect(within(chips).getAllByRole('button')).toHaveLength(1);
    await waitFor(() => expect(mood.mock.calls.at(-1)?.[0]).toEqual({ tags: ['ALLEY_WALK'], avoid: [], date: '2026-10-17' }));
  });

  it('새 문장 해석이 실패하면 이전 칩을 남기지 않는다', async () => {
    const mood = mockMood();
    renderPage();
    await search('바다');
    await screen.findByRole('group', { name: '해석된 조건' });

    mood.mockRejectedValueOnce(new ApiError({ id: 'TIMEOUT' }));
    await userEvent.clear(screen.getByLabelText('원하는 분위기'));
    await search('골목');

    expect(await screen.findByRole('alert')).toHaveTextContent('추천을 불러오지 못했어요');
    expect(screen.queryByRole('group', { name: '해석된 조건' })).not.toBeInTheDocument();
  });

  it('해석은 됐지만 추천이 실패하면 칩은 두고 오류를 안내한다', async () => {
    const mood = mockMood();
    mood.mockImplementation(async (body: MoodRequest): Promise<MoodResponse> => {
      if (body.text !== undefined) return { tags: moodTags, avoid: moodAvoid, places: [] };
      throw new ApiError({ id: 'TIMEOUT' });
    });
    renderPage();
    await search();

    expect(await screen.findByRole('alert')).toHaveTextContent('추천을 불러오지 못했어요');
    expect(screen.getByRole('group', { name: '해석된 조건' })).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: '추천 장소' })).not.toBeInTheDocument();
  });

  it('호출이 실패하면 오류와 검색으로 담는 방법을 안내한다', async () => {
    vi.spyOn(recommendApi, 'mood').mockRejectedValue(new ApiError({ id: 'TIMEOUT' }));
    renderPage();
    await search();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('추천을 불러오지 못했어요');
    expect(alert).toHaveTextContent('여행 시작 화면에서 검색해 담을 수 있어요');
  });

  it('표시명을 모르는 태그 코드는 화면에 내보내지 않는다', async () => {
    const [first] = moodPlaces;
    mockMood([{ ...first!, evidence: { matchedTags: ['SEA_VIEW', 'UNKNOWN_CODE'], excerpt: '근거 예시', source: null } }]);
    renderPage();
    await search();
    expect(await screen.findByText('바다 전망 — “근거 예시”')).toBeInTheDocument();
    expect(screen.queryByText(/UNKNOWN_CODE/)).not.toBeInTheDocument();
  });

  it('이미 담겨 있던 곳은 이 화면에서 담은 수에 넣지 않는다', async () => {
    useTripDraft.getState().addPinned({
      kind: 'PUBLIC',
      placeId: PLACE_IDS.huinnyeoul,
      name: '흰여울문화마을',
      coords: { lat: 35.0784, lng: 129.0453 },
    });
    mockMood();
    renderPage();
    await search();
    expect(await screen.findByRole('button', { name: '흰여울문화마을 빼기' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '돌아가기' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '청사포 담기' }));
    expect(screen.getByRole('button', { name: '1곳 담고 돌아가기' })).toBeInTheDocument();
  });

  it.each(['2026-02-31', '10/17'])('여행 시작일(%s)이 날짜가 아니면 오늘을 기준일로 보낸다', async (start) => {
    useTripDraft.getState().setConditions({ dates: { start, end: start } });
    vi.useFakeTimers({ toFake: ['Date'], now: new Date(2026, 10, 17, 9) });
    try {
      const mood = mockMood();
      renderPage();
      await search();
      await screen.findByRole('list', { name: '추천 장소' });
      expect(mood.mock.calls[0]![0]).toMatchObject({ date: '2026-11-17' });
    } finally {
      vi.useRealTimers();
    }
  });

  describe('고른 분위기를 여행 조건에 담는다(FR-015)', () => {
    it('해석된 칩을 담고, 칩을 끄고 켜면 바로 고친다', async () => {
      const mood = mockMood();
      renderPage();
      await search();
      await screen.findByRole('list', { name: '추천 장소' });
      expect(useTripDraft.getState().mood).toEqual({ tags: moodTags, avoid: moodAvoid });
      expect(useTripDraft.getState().conditions.prefs).toEqual({ tags: ['SEA_VIEW', 'ALLEY_WALK'], avoid: ['실내 제외'] });

      const chips = screen.getByRole('group', { name: '해석된 조건' });
      await userEvent.click(within(chips).getByRole('button', { name: /골목·산책/ }));
      await userEvent.click(within(chips).getByRole('button', { name: /실내 제외/ }));
      expect(useTripDraft.getState().conditions.prefs).toEqual({ tags: ['SEA_VIEW'] });

      // 끈 칩을 다시 켜면 그 태그가 다시 담기고, 그 태그로 추천을 다시 받는다.
      await userEvent.click(within(chips).getByRole('button', { name: /골목·산책/ }));
      expect(useTripDraft.getState().conditions.prefs).toEqual({ tags: ['SEA_VIEW', 'ALLEY_WALK'] });
      await waitFor(() =>
        expect(mood.mock.calls.at(-1)![0]).toEqual({ tags: ['SEA_VIEW', 'ALLEY_WALK'], avoid: [], date: '2026-10-17' }),
      );

      await userEvent.click(within(chips).getByRole('button', { name: /골목·산책/ }));
      await userEvent.click(within(chips).getByRole('button', { name: /바다 전망/ }));
      expect(useTripDraft.getState().mood).toBeNull();
      expect(useTripDraft.getState().conditions.prefs).toBeUndefined();
    });

    it('다시 들어오면 전에 고른 칩을 켠 채로 추천을 다시 받는다', async () => {
      useTripDraft.getState().setMood({ tags: [moodTags[0]!], avoid: ['실내 제외'] });
      const mood = mockMood();
      renderPage();

      const chips = screen.getByRole('group', { name: '해석된 조건' });
      expect(within(chips).getByRole('button', { name: /바다 전망/ })).toHaveAttribute('aria-pressed', 'true');
      expect(within(chips).getByRole('button', { name: /실내 제외/ })).toHaveAttribute('aria-pressed', 'true');
      expect(await screen.findByRole('list', { name: '추천 장소' })).toBeInTheDocument();
      expect(mood.mock.calls.map(([body]) => body)).toEqual([{ tags: ['SEA_VIEW'], avoid: ['실내 제외'], date: '2026-10-17' }]);
    });

    it('읽지 못한 문장으로 다시 찾으면 전에 고른 분위기를 지운다', async () => {
      useTripDraft.getState().setMood({ tags: [moodTags[0]!], avoid: [] });
      vi.spyOn(recommendApi, 'mood').mockImplementation(async (body: MoodRequest) =>
        body.text !== undefined ? { tags: [], avoid: [], places: [] } : { tags: [], avoid: [], places: moodPlaces },
      );
      renderPage();
      await search('아무 말');
      expect(await screen.findByText(/문장에서 분위기를 읽지 못했어요/)).toBeInTheDocument();
      expect(useTripDraft.getState().mood).toBeNull();
    });
  });

  it('여행 날짜가 없으면 오늘을 기준일로 보낸다', async () => {
    useTripDraft.getState().reset();
    vi.useFakeTimers({ toFake: ['Date'], now: new Date(2026, 10, 17, 9) });
    try {
      const mood = mockMood();
      renderPage();
      await search();
      await screen.findByRole('list', { name: '추천 장소' });
      expect(mood.mock.calls[0]![0]).toMatchObject({ date: '2026-11-17' });
    } finally {
      vi.useRealTimers();
    }
  });
});
