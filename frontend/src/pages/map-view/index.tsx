import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { placesApi, toApiError, tripsApi } from '@/api';
import { rememberKakaoPlace, resolveBlockPlace } from '@/api/kakaoSession';
import { paths } from '@/app/paths';
import { Badge, Button, EmptyState, ErrorState, LoadingState } from '@/components';
import { CrowdBadge } from '@/features/crowd/CrowdBadge';
import { blockRole, formatDuration, legBetween, legLabel } from '@/features/itinerary/format';
import { BackIcon, LockIcon } from '@/features/itinerary/icons';
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
  const sheet = useRef<HTMLElement>(null);

  // 선택 카드는 시트 맨 위에 나오므로, 목록 아래쪽을 눌렀을 때도 보이게 시트를 올린다.
  useEffect(() => {
    if (selectedId) sheet.current?.scrollTo?.({ top: 0, behavior: 'smooth' });
  }, [selectedId]);

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
      setNotice(`${place.name}을(를) ${day?.dayNo ?? dayNo}일차 코스에 추가했어요.`);
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
  // 혼잡 신호가 없으면 grade=null 로 '정보 부족'을 보여 준다(NFR-012).
  const crowdOf = (blockId: string) => {
    const crowd = day.crowd.find((item) => item.blockId === blockId);
    return { grade: crowd?.grade ?? null, confidence: crowd?.confidence };
  };
  const alerts = [...visibleViolations.map((item) => item.cause), ...currentSchedule.conflicts.map((item) => item.cause)];

  return <main className={styles.page}>
    <h1 className={styles.srOnly}>지도 보기</h1>
    <KakaoMap className={styles.map} blocks={blocks} legs={day.legs} selectedId={selectedId} onSelect={setSelectedId} onLongPress={findNearby} />

    <div className={styles.overlay}>
      <div className={styles.topRow}>
        <Link to={paths.timeline(tripId)} className={styles.roundButton} aria-label="코스 타임라인으로"><BackIcon /></Link>
        {currentSchedule.days.length > 0 && <nav className={styles.days} aria-label="여행 일차">
          {currentSchedule.days.map((item) => <button key={item.dayNo} type="button" className={styles.dayChip} aria-pressed={day.dayNo === item.dayNo} onClick={() => { setDayNo(item.dayNo); setSelectedId(null); setCandidates([]); }}>{item.dayNo}일차</button>)}
        </nav>}
      </div>
      <p className={styles.hint}>지도를 길게 누르면 그 위치의 장소를 찾아요</p>
    </div>

    <section ref={sheet} className={styles.sheet} aria-label="지도 정보">
      <span className={styles.handle} aria-hidden="true" />
      {notice ? <p role="status" className={styles.notice}>{notice}</p> : null}
      {busy ? <p role="status" className={styles.muted}>처리 중이에요…</p> : null}
      {alerts.length > 0 ? <section role="alert" aria-label="일정 경고" className={styles.alerts}>
        <h2>일정 경고 {alerts.length}건</h2>
        <ul>{alerts.map((cause, index) => <li key={`${index}-${cause}`}>{cause}</li>)}</ul>
      </section> : null}

      {selected ? <section className={styles.selectedCard} aria-label="선택한 장소">
        <p className={styles.eyebrow}>{blocks.indexOf(selected) + 1}번째 장소</p>
        <h2 className={styles.candidateName}>{resolveBlockPlace(selected.place)?.name ?? '다시 선택 필요'}</h2>
        <p className={styles.muted}>
          {[blockRole(selected), selected.place.source === 'PUBLIC' ? selected.place.category : null, `${selected.arriveAt ?? '시각 미정'}–${selected.departAt ?? '시각 미정'}`, `체류 ${formatDuration(selected.stayMin)}`].filter(Boolean).join(' · ')}
        </p>
        <div className={styles.badges}>
          <Badge kind={selected.place.source === 'PUBLIC' ? 'detail' : 'basic'} />
          <CrowdBadge {...crowdOf(selected.id)} />
          {selected.isFixed ? <span className={styles.fixed}><LockIcon />고정</span> : null}
          {selected.warnings.map((item, i) => <Badge key={i} kind="needsCheck" label={item.cause} />)}
        </div>
        <div className={styles.actions}>
          <Button variant="outline" onClick={() => setSelectedId(null)}>닫기</Button>
          <Link to={paths.timeline(tripId)} className={styles.primaryLink}>타임라인에서 편집</Link>
        </div>
      </section> : null}
      {candidates.length > 0 ? <section aria-label="주변 장소">
        <p className={styles.eyebrow}>지도에서 고른 곳</p>
        <ul className={styles.candidates}>{candidates.map((place) => <li key={place.kakaoPlaceId}>
          <div>
            <h2 className={styles.candidateName}>{place.name}</h2>
            {place.address ? <p className={styles.muted}>{place.address}</p> : null}
            <Badge kind={place.placeId ? 'detail' : 'basic'} />
          </div>
          <Button disabled={busy} onClick={() => void addPlace(place)}>꼭 갈 곳에 추가</Button>
        </li>)}</ul>
        <Button variant="ghost" onClick={() => setCandidates([])}>닫기</Button>
      </section> : <section aria-label="일정 장소">
        <h2 className={styles.sheetTitle}>{day.dayNo}일차 장소 순서</h2>
        {blocks.length === 0 ? <p className={styles.muted}>아직 장소가 없어요. 지도에서 위치를 길게 눌러 추가하세요.</p> : null}
        <ol className={styles.stops}>{blocks.map((block, index) => {
          const place = resolveBlockPlace(block.place);
          const leg = legBetween(day.legs, blocks[index - 1], block);
          return <li key={block.id}>
            {leg ? <p className={styles.leg}>{legLabel(leg)}</p> : null}
            <button type="button" className={styles.stop} aria-pressed={selectedId === block.id} onClick={() => setSelectedId(block.id)}>
              <span className={styles.stopNo} aria-hidden="true">{index + 1}</span>
              <span className={styles.stopBody}>
                <span className={styles.stopName}>{place?.name ?? '다시 선택 필요'}{block.isFixed ? <span className={styles.stopLock}><LockIcon /><span className={styles.srOnly}>고정</span></span> : null}</span>
                <span className={styles.stopMeta}>{blockRole(block)} · 체류 {formatDuration(block.stayMin)}</span>
                <span className={styles.badges}>
                  <CrowdBadge {...crowdOf(block.id)} />
                  {block.warnings.length > 0 ? <Badge kind="needsCheck" label={`확인 필요 ${block.warnings.length}건`} /> : null}
                </span>
              </span>
              <span className={styles.stopTime}>{block.arriveAt ?? '--:--'}</span>
            </button>
            {/* D6: 이번 접속에서 고르지 않은 카카오 장소는 place_url을 외부 브라우저로 연다. */}
            {!place && block.place.source === 'KAKAO' ? <a className={styles.placeLink} href={block.place.placeUrl} target="_blank" rel="noopener noreferrer">카카오맵에서 장소 확인 (새 창)</a> : null}
          </li>;
        })}</ol>
        <p className={styles.footnote}>선은 방문 순서만 이어요. 실제 도로·대중교통 경로가 아니에요.</p>
      </section>}
    </section>
  </main>;
}
