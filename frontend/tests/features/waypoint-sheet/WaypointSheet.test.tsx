import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { tripsApi } from '@/api';
import { placeSummaries } from '@/api/mock/fixtures/places';
import { schedule } from '@/api/mock/fixtures/schedule';
import { WaypointSheet, type WaypointSheetProps } from '@/features/waypoint-sheet/WaypointSheet';
import type { SuggestWaypointsResponse, WaypointCandidate } from '@/types/api';

const candidate: WaypointCandidate = {
  place: placeSummaries.gamcheon, detourMin: 10, stayMin: 40, crowd: null, reason: '공공 장소 추천 이유',
};
function props(): WaypointSheetProps {
  return { tripId: 'trip', between: { fromBlockId: 'a', toBlockId: 'b' }, disabled: false, onChange: vi.fn(async (action) => { await action(); }), onClose: vi.fn() };
}
function deferred() {
  let resolve!: (value: SuggestWaypointsResponse) => void;
  const promise = new Promise<SuggestWaypointsResponse>((done) => { resolve = done; });
  return { promise, resolve };
}

describe('WaypointSheet', () => {
  it('기본 15분으로 조회하고 이동·체류·혼잡 부족·추천 이유를 표시한다', async () => {
    const suggest = vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [candidate] });
    render(<WaypointSheet {...props()} />);
    expect(await screen.findByText(candidate.place.name)).toBeInTheDocument();
    expect(suggest).toHaveBeenCalledWith('trip', { fromBlockId: 'a', toBlockId: 'b', thresholdMin: 15 }, { signal: expect.any(AbortSignal) });
    expect(screen.getByText('추가 이동 10분 · 체류 40분')).toBeInTheDocument();
    expect(screen.getByText('정보 부족')).toBeInTheDocument();
    expect(screen.getByText(candidate.reason)).toBeInTheDocument();
    expect(screen.getByLabelText('15분')).toBeChecked();
  });

  it('10/30분 변경은 해당 임계값으로 다시 조회하고 빈 결과 안내를 제공한다', async () => {
    const suggest = vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [] });
    render(<WaypointSheet {...props()} />);
    expect(await screen.findByText('추가할 곳 없음')).toBeInTheDocument();
    expect(screen.getByText('우회 허용 시간을 늘려 다시 찾아보세요.')).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText('10분'));
    await waitFor(() => expect(suggest).toHaveBeenLastCalledWith('trip', expect.objectContaining({ thresholdMin: 10 }), expect.anything()));
    await userEvent.click(screen.getByLabelText('30분'));
    expect(await screen.findByText('다른 구간에서 찾아보세요.')).toBeInTheDocument();
    expect(suggest).toHaveBeenLastCalledWith('trip', expect.objectContaining({ thresholdMin: 30 }), expect.anything());
  });

  it('수락은 부모 변경 핸들러를 통해 기존 API-006 필드만 전달한다', async () => {
    vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [candidate] });
    const add = vi.spyOn(tripsApi, 'addBlock').mockResolvedValue({ schedule, violations: [] });
    const input = props();
    render(<WaypointSheet {...input} />);
    await userEvent.click(await screen.findByRole('button', { name: `${candidate.place.name} 경유지로 추가` }));
    expect(input.onChange).toHaveBeenCalledTimes(1);
    expect(add).toHaveBeenCalledExactlyOnceWith('trip', { place: { placeId: candidate.place.id }, fromBlockId: 'a', toBlockId: 'b', isFixed: false, origin: 'SUGGESTED', stayMin: candidate.stayMin });
  });

  it('부모가 편집 중이면 임계값과 추가 버튼을 잠근다', async () => {
    vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [candidate] });
    render(<WaypointSheet {...props()} disabled />);
    expect(await screen.findByRole('button', { name: `${candidate.place.name} 경유지로 추가` })).toBeDisabled();
    expect(screen.getByLabelText('10분')).toBeDisabled();
  });

  it('최대 3개만 서버 순서대로 표시한다', async () => {
    vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [1, 2, 3, 4].map((n) => ({ ...candidate, place: { ...candidate.place, id: `id${n}`, name: `후보${n}` } })) });
    render(<WaypointSheet {...props()} />);
    await screen.findByText('후보1');
    expect(screen.getAllByRole('heading', { level: 3 }).map((node) => node.textContent)).toEqual(['후보1', '후보2', '후보3']);
    expect(screen.queryByText('후보4')).not.toBeInTheDocument();
  });

  it('조회 오류는 재시도할 수 있고 원시 예외 내용을 표시하지 않는다', async () => {
    vi.spyOn(tripsApi, 'suggestWaypoints').mockRejectedValueOnce(new Error('secret raw payload')).mockResolvedValueOnce({ candidates: [candidate] });
    render(<WaypointSheet {...props()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('경유지를 불러오지 못했어요.');
    expect(screen.queryByText(/secret raw/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText(candidate.place.name)).toBeInTheDocument();
  });

  it('임계값이 바뀌면 이전 요청을 취소하고 늦은 결과를 무시한다', async () => {
    const old = deferred();
    const suggest = vi.spyOn(tripsApi, 'suggestWaypoints').mockReturnValueOnce(old.promise).mockResolvedValueOnce({ candidates: [] });
    render(<WaypointSheet {...props()} />);
    expect(screen.getByRole('status')).toHaveTextContent('경유지를 찾는 중');
    await userEvent.click(screen.getByLabelText('30분'));
    await screen.findByText('추가할 곳 없음');
    expect(suggest.mock.calls[0]![2]!.signal!.aborted).toBe(true);
    await act(async () => old.resolve({ candidates: [candidate] }));
    expect(screen.queryByText(candidate.place.name)).not.toBeInTheDocument();
  });

  it('다른 구간으로 바꾸면 기본 임계값으로 재조회하고 이전 후보를 숨긴다', async () => {
    const next = deferred();
    vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValueOnce({ candidates: [candidate] }).mockResolvedValueOnce({ candidates: [candidate] }).mockReturnValueOnce(next.promise);
    const input = props();
    const view = render(<WaypointSheet {...input} />);
    await screen.findByText(candidate.place.name);
    await userEvent.click(screen.getByLabelText('30분'));
    await screen.findByText(candidate.place.name);
    view.rerender(<WaypointSheet {...input} between={{ fromBlockId: 'b', toBlockId: 'c' }} />);
    expect(screen.getByLabelText('15분')).toBeChecked();
    expect(screen.queryByText(candidate.place.name)).not.toBeInTheDocument();
    await act(async () => next.resolve({ candidates: [] }));
  });

  it('닫기는 부모에게 전달하고 언마운트하면 요청을 취소한다', async () => {
    const pending = deferred();
    const suggest = vi.spyOn(tripsApi, 'suggestWaypoints').mockReturnValue(pending.promise);
    const input = props();
    const view = render(<WaypointSheet {...input} />);
    await userEvent.click(screen.getByRole('button', { name: '닫기' }));
    expect(input.onClose).toHaveBeenCalledOnce();
    view.unmount();
    expect(suggest.mock.calls[0]![2]!.signal!.aborted).toBe(true);
    await act(async () => pending.resolve({ candidates: [candidate] }));
  });
});


it('삽입 실패를 시트 내부에 표시하고 같은 후보로 재시도한다', async () => {
  vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [candidate] });
  const add = vi.spyOn(tripsApi, 'addBlock').mockRejectedValueOnce(new Error('private raw error')).mockResolvedValueOnce({ schedule, violations: [] });
  const input = props();
  input.onChange = vi.fn(async (action) => { try { await action(); input.onClose(); } catch { /* parent owns timeline error */ } });
  render(<WaypointSheet {...input} />);
  const button = await screen.findByRole('button', { name: `${candidate.place.name} 경유지로 추가` });
  await userEvent.click(button);
  const alert = await screen.findByRole('alert');
  expect(screen.getByRole('dialog').contains(alert)).toBe(true);
  expect(alert).not.toHaveTextContent('private raw error');
  expect(input.onClose).not.toHaveBeenCalled();
  await userEvent.click(button);
  await waitFor(() => expect(input.onClose).toHaveBeenCalledOnce());
  expect(add).toHaveBeenCalledTimes(2);
});

it('빈 추천에서도 직접 검색 진입점을 제공하며 삽입하지 않는다', async () => {
  vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [] });
  const add = vi.spyOn(tripsApi, 'addBlock');
  const direct = vi.fn();
  render(<WaypointSheet {...props()} onDirectSearch={direct} />);
  await screen.findByText('추가할 곳 없음');
  await userEvent.click(screen.getByRole('button', { name: '직접 검색해서 넣기' }));
  expect(direct).toHaveBeenCalledOnce();
  expect(add).not.toHaveBeenCalled();
});
