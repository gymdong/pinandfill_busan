import { useCallback, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { placesApi, toApiError, tripsApi } from '@/api';
import { rememberKakaoPlace, resolveBlockPlace } from '@/api/kakaoSession';
import { paths } from '@/app/paths';
import { EmptyState, ErrorState, LoadingState } from '@/components';
import { useApi } from '@/hooks/useApi';
import { KakaoMap } from '@/map/KakaoMap';
import type { Coords, PlaceSearchItem, Schedule, Violation } from '@/types/api';
import styles from './MapView.module.css';

export default function MapViewPage() {
  const { tripId = '' } = useParams();
  return <MapViewContent key={tripId} tripId={tripId} />;
}

function MapViewContent({ tripId }: { tripId: string }) {
  const fetchTrip = useCallback((signal: AbortSignal) => tripsApi.get(tripId, { signal }), [tripId]);
  const request = useApi(fetchTrip);
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [dayNo, setDayNo] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<PlaceSearchItem[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [violations, setViolations] = useState<Violation[]>([]);

  const currentSchedule = useMemo(() => schedule ?? (request.status === 'success' ? request.data.schedule ?? { days: [], violations: [], conflicts: [] } : null), [schedule, request.status, request.data]);
  const day = useMemo(() => currentSchedule?.days.find((item) => item.dayNo === dayNo) ?? currentSchedule?.days[0] ?? (request.status === 'success' ? { dayNo: 1, date: request.data.trip.dates.start, blocks: [], legs: [], crowd: [], weather: [] } : null), [currentSchedule, dayNo, request.status, request.data]);
  const blocks = useMemo(() => day ? [...day.blocks].sort((a, b) => a.seq - b.seq) : [], [day]);

  const findNearby = useCallback(async (coords: Coords) => {
    setBusy(true); setCandidates([]); setNotice(null);
    try {
      const result = await placesApi.at(coords);
      setCandidates(result.places);
      if (result.places.length === 0) setNotice('이 위치에서 찾은 장소가 없어요.');
    } catch (error) { setNotice(toApiError(error).message); }
    finally { setBusy(false); }
  }, []);

  const addPlace = async (place: PlaceSearchItem) => {
    setBusy(true); setNotice(null);
    try {
      // D6: 이름·좌표는 현재 접속 메모리에만 저장한다.
      if (!place.placeId) rememberKakaoPlace(place.kakaoPlaceId, { name: place.name, coords: place.coords });
      const result = await tripsApi.addBlock(tripId, {
        place: place.placeId ? { placeId: place.placeId } : { kakaoPlaceId: place.kakaoPlaceId, placeUrl: place.placeUrl },
        isFixed: false, origin: 'USER', dayNo: day?.dayNo ?? dayNo,
      });
      setSchedule(result.schedule); setViolations(result.violations); setCandidates([]);
      setNotice(`${place.name}을(를) 핵심지에 추가했어요.`);
    } catch (error) { setNotice(toApiError(error).message); }
    finally { setBusy(false); }
  };

  if (request.status === 'loading') return <LoadingState message="지도를 준비하고 있어요" />;
  if (request.status === 'error') return <ErrorState message={request.error.message} onRetry={request.reload} />;
  if (!currentSchedule || !day) return <EmptyState title="일정을 불러오지 못했어요" action={<Link to={paths.timeline(tripId)}>일정으로 돌아가기</Link>} />;

  const selected = blocks.find((block) => block.id === selectedId);
  const visibleViolations = [...violations, ...currentSchedule.violations].filter((item, index, all) =>
    all.findIndex((candidate) => candidate.type === item.type && candidate.cause === item.cause) === index,
  );

  return <main className={styles.page}>
    <header className={styles.header}><Link to={paths.timeline(tripId)}>← 코스 타임라인</Link><h1>UI-06 지도 보기</h1></header>
    {currentSchedule.days.length > 0 ? <nav className={styles.days} aria-label="여행 일차">{currentSchedule.days.map((item) => <button key={item.dayNo} type="button" aria-current={day.dayNo === item.dayNo ? 'date' : undefined} onClick={() => { setDayNo(item.dayNo); setSelectedId(null); setCandidates([]); }}>{item.dayNo}일차</button>)}</nav> : null}
    <KakaoMap blocks={blocks} legs={day.legs} selectedId={selectedId} onSelect={setSelectedId} onLongPress={findNearby} />
    <p className={styles.hint}>선은 장소 순서만 나타내며 실제 도로·대중교통 경로가 아닙니다. 지도를 길게 누르면 주변 장소를 찾습니다.</p>
    {notice ? <p role="status" className={styles.notice}>{notice}</p> : null}
    {visibleViolations.length > 0 || currentSchedule.conflicts.length > 0 ? <section role="alert" aria-label="일정 경고"><h2>일정 경고</h2><ul>{visibleViolations.map((item, index) => <li key={`v-${index}`}>{item.cause}</li>)}{currentSchedule.conflicts.map((item, index) => <li key={`c-${index}`}>{item.cause}</li>)}</ul></section> : null}
    {busy ? <p role="status">처리 중이에요…</p> : null}
    {candidates.length > 0 ? <section aria-label="주변 장소"><h2>주변 장소</h2><ul className={styles.list}>{candidates.map((place) => <li key={place.kakaoPlaceId}><span>{place.name}</span><button type="button" disabled={busy} onClick={() => void addPlace(place)}>핵심지에 추가</button></li>)}</ul></section> : null}
    <section aria-label="일정 장소"><h2>{day.dayNo}일차 장소 순서</h2>{blocks.length === 0 ? <p>아직 장소가 없어요. 지도에서 위치를 길게 눌러 추가하세요.</p> : null}<ol className={styles.list}>{blocks.map((block, index) => {
      const place = resolveBlockPlace(block.place);
      const previous = blocks[index - 1];
      const leg = previous ? day.legs.find((item) => item.fromBlockId === previous.id && item.toBlockId === block.id) : null;
      return <li key={block.id}>
        {leg ? <p className={styles.leg}>{leg.mode === 'TRANSIT' ? '대중교통' : leg.mode === 'WALK' ? '도보' : '자동차'} · {leg.durationMin === null ? '이동시간 확인 필요' : `${leg.durationMin}분`}{leg.source === 'ESTIMATED' ? ' (추정)' : ''}</p> : null}
        <button type="button" className={selectedId === block.id ? styles.selected : ''} aria-pressed={selectedId === block.id} onClick={() => setSelectedId(block.id)}>{index + 1}. {place?.name ?? '다시 선택 필요'} · {block.arriveAt ?? '시각 미정'}</button>
        {/* D6: 이번 접속에서 고르지 않은 카카오 장소는 place_url을 외부 브라우저로 연다. */}
        {!place && block.place.source === 'KAKAO' ? <a className={styles.placeLink} href={block.place.placeUrl} target="_blank" rel="noopener noreferrer">카카오맵에서 장소 확인 (새 창)</a> : null}
      </li>;
    })}</ol>{selected ? <p className={styles.notice}>선택한 장소: {resolveBlockPlace(selected.place)?.name ?? '다시 선택 필요'}</p> : null}</section>
  </main>;
}
