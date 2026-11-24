import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ApiError, placesApi } from '@/api';
import { searchItems } from '@/api/mock/fixtures/places';
import { PlaceSearch, toPinnedPlace } from '@/features/place-search';
import { pinnedKey } from '@/store/tripDraft';

const park = searchItems[0]!;
const cafe = searchItems[2]!;

async function searchFor(query: string) {
  await userEvent.type(screen.getByLabelText('장소 검색'), query);
  await userEvent.click(screen.getByRole('button', { name: '검색' }));
}

describe('장소 검색', () => {
  it('매칭 배지와 영업시간 확인 필요 배지를 결과마다 보여 준다(FR-001)', async () => {
    vi.spyOn(placesApi, 'search').mockResolvedValue({ places: [{ ...park, hoursStatus: 'KNOWN' }, cafe] });
    render(<PlaceSearch pickedKeys={new Set()} onPick={() => {}} />);
    await searchFor('민락');

    const [matched, unmatched] = within(await screen.findByRole('list', { name: '검색 결과' })).getAllByRole('listitem');
    expect(within(matched!).getByText('상세 정보 있음')).toBeInTheDocument();
    expect(within(matched!).queryByText('영업시간 확인 필요')).not.toBeInTheDocument();
    expect(within(matched!).getByText('공원 · 수영구 광안해변로')).toBeInTheDocument();
    expect(within(unmatched!).getByText('기본 정보만')).toBeInTheDocument();
    expect(within(unmatched!).getByText('영업시간 확인 필요')).toBeInTheDocument();
  });

  it('검색어는 앞뒤 공백을 빼고 제출할 때만 보낸다', async () => {
    const search = vi.spyOn(placesApi, 'search').mockResolvedValue({ places: [] });
    render(<PlaceSearch pickedKeys={new Set()} onPick={() => {}} />);
    expect(screen.getByRole('button', { name: '검색' })).toBeDisabled();
    await userEvent.type(screen.getByLabelText('장소 검색'), ' 민락 {Enter}');
    expect(search).toHaveBeenCalledTimes(1);
    expect(search.mock.calls[0]![0]).toEqual({ q: '민락' });
  });

  it('결과를 누르면 담고, 담긴 결과를 다시 누르면 뺀다', async () => {
    vi.spyOn(placesApi, 'search').mockResolvedValue({ places: [park, cafe] });
    const onPick = vi.fn();
    const onUnpick = vi.fn();
    render(<PlaceSearch pickedKeys={new Set([pinnedKey(toPinnedPlace(cafe))])} onPick={onPick} onUnpick={onUnpick} />);
    await searchFor('민락');

    const parkButton = await screen.findByRole('button', { name: /민락수변공원/ });
    const cafeButton = screen.getByRole('button', { name: /카페/ });
    expect(parkButton).toHaveAttribute('aria-pressed', 'false');
    expect(cafeButton).toHaveAttribute('aria-pressed', 'true');
    expect(within(cafeButton).getByText('✓ 담김')).toBeInTheDocument();

    await userEvent.click(parkButton);
    await userEvent.click(cafeButton);
    expect(onPick).toHaveBeenCalledExactlyOnceWith(park);
    expect(onUnpick).toHaveBeenCalledExactlyOnceWith(cafe);
  });

  it('결과가 없으면 검색어와 다른 방법 안내를 보여 준다', async () => {
    vi.spyOn(placesApi, 'search').mockResolvedValue({ places: [] });
    render(<PlaceSearch pickedKeys={new Set()} onPick={() => {}} fallbackHint="지도에서 골라 주세요" />);
    await searchFor('없는곳');
    const notice = await screen.findByText(/검색 결과가 없어요/);
    expect(notice).toHaveTextContent('‘없는곳’ 검색 결과가 없어요.');
    expect(screen.getByText('지도에서 골라 주세요')).toBeInTheDocument();
  });

  it('검색이 실패하면 오류 문구와 안내를 보여 주고 다시 검색할 수 있다(ERR-003)', async () => {
    const search = vi
      .spyOn(placesApi, 'search')
      .mockRejectedValueOnce(new ApiError({ id: 'ERR-003', status: 503 }))
      .mockResolvedValue({ places: [park] });
    render(<PlaceSearch pickedKeys={new Set()} onPick={() => {}} fallbackHint="지도에서 골라 주세요" />);
    await searchFor('민락');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('장소 검색이 잠시 안 돼요');
    expect(alert).toHaveTextContent('지도에서 골라 주세요');

    await userEvent.click(within(alert).getByRole('button', { name: '다시 검색' }));
    expect(await screen.findByRole('button', { name: /민락수변공원/ })).toBeInTheDocument();
    expect(search).toHaveBeenCalledTimes(2);
  });

  it('결과 닫기를 누르면 결과가 사라지고 검색어는 남는다', async () => {
    vi.spyOn(placesApi, 'search').mockResolvedValue({ places: [park, cafe] });
    render(<PlaceSearch pickedKeys={new Set()} onPick={() => {}} />);
    await searchFor('민락');
    expect(await screen.findByText('‘민락’ 검색 결과 2곳')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '결과 닫기' }));
    expect(screen.queryByRole('list', { name: '검색 결과' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '결과 닫기' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('장소 검색')).toHaveValue('민락');
  });

  it('Esc 를 누르거나 검색어를 모두 지우면 결과를 닫는다', async () => {
    vi.spyOn(placesApi, 'search').mockResolvedValue({ places: [park] });
    render(<PlaceSearch pickedKeys={new Set()} onPick={() => {}} />);
    await searchFor('민락');
    await screen.findByRole('list', { name: '검색 결과' });
    await userEvent.type(screen.getByLabelText('장소 검색'), '{Escape}');
    expect(screen.queryByRole('list', { name: '검색 결과' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '검색' }));
    await screen.findByRole('list', { name: '검색 결과' });
    await userEvent.clear(screen.getByLabelText('장소 검색'));
    expect(screen.queryByRole('list', { name: '검색 결과' })).not.toBeInTheDocument();
  });

  it('결과가 없을 때와 오류일 때도 닫을 수 있다', async () => {
    vi.spyOn(placesApi, 'search').mockResolvedValue({ places: [] });
    render(<PlaceSearch pickedKeys={new Set()} onPick={() => {}} />);
    await searchFor('없는곳');
    await screen.findByText('‘없는곳’ 검색 결과가 없어요.');
    await userEvent.click(screen.getByRole('button', { name: '결과 닫기' }));
    expect(screen.queryByText('‘없는곳’ 검색 결과가 없어요.')).not.toBeInTheDocument();
  });
});
