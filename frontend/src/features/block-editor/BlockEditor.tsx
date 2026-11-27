import { useEffect, useRef, useState } from 'react';
import { placesApi, rememberKakaoPlace, toApiError, tripsApi } from '@/api';
import { Button } from '@/components';
import { formatDuration } from '@/features/itinerary/format';
import { STAY_OPTIONS } from '@/features/place-search';
import type { Block, PlaceSearchItem, Schedule } from '@/types/api';
import styles from './BlockEditor.module.css';

type Change = (action: () => Promise<{ schedule: Schedule }>) => Promise<void>;

export function BlockEditor({ tripId, block, between, dayNo, disabled, onChange }: {
  tripId: string;
  block?: Block;
  between?: { fromBlockId: string; toBlockId: string };
  /** 앵커 없이 추가할 때 끝에 붙일 일차 */
  dayNo?: number;
  disabled: boolean;
  onChange: Change;
}) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PlaceSearchItem[]>([]);
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [stayMin, setStayMin] = useState(block?.stayMin ?? 30);
  const [seq, setSeq] = useState(block?.seq ?? 1);
  // 고정 장소를 빼는 것은 되돌리기 전까지 고정 시각을 잃는 일이라 한 번 더 묻는다.
  const [confirmRemove, setConfirmRemove] = useState(false);
  const cancelRef = useRef<HTMLButtonElement>(null);
  // '일정에서 빼기' 버튼이 확인 영역으로 바뀌면 포커스를 '취소'로 옮긴다(키보드 사용자가 길을 잃지 않게).
  useEffect(() => { if (confirmRemove) cancelRef.current?.focus(); }, [confirmRemove]);
  // 후보별(kakaoPlaceId) 고른 체류시간과 안내. 서버는 체류시간 기본값을 만들지 않는다(#18 PM 결정 4, 지도 UI-06과 같음).
  const [stays, setStays] = useState<Record<string, number>>({});
  const [stayErrors, setStayErrors] = useState<Record<string, string>>({});
  // 공공 DB 장소라도 서버가 체류시간 근거가 없다고 알려 준(fields.stayMin) 후보
  const [askStay, setAskStay] = useState<ReadonlySet<string>>(new Set());

  // 공공 DB에 없는 카카오 장소는 체류시간 근거가 없어 사용자가 고른다.
  const needsStay = (place: PlaceSearchItem) => !place.placeId || askStay.has(place.kakaoPlaceId);

  const addPlace = (place: PlaceSearchItem) => {
    const key = place.kakaoPlaceId;
    const chosen = stays[key];
    if (needsStay(place) && !chosen) {
      setStayErrors((prev) => ({ ...prev, [key]: '머무를 시간을 골라 주세요.' }));
      return;
    }
    if (!place.placeId) rememberKakaoPlace(place.kakaoPlaceId, { name: place.name, coords: place.coords });
    void onChange(async () => {
      try {
        return await tripsApi.addBlock(tripId, {
          place: place.placeId ? { placeId: place.placeId } : { kakaoPlaceId: place.kakaoPlaceId, placeUrl: place.placeUrl },
          isFixed: false, origin: 'USER', ...(between ?? (dayNo === undefined ? {} : { dayNo })),
          ...(chosen ? { stayMin: chosen } : {}),
        });
      } catch (cause) {
        // 부모가 오류를 삼키므로 여기서 먼저 보고, 서버가 체류시간을 물으면 그 후보에 고르는 칸을 띄운다.
        const stayMessage = toApiError(cause).fields?.stayMin;
        if (stayMessage) {
          setAskStay((prev) => new Set(prev).add(key));
          setStayErrors((prev) => ({ ...prev, [key]: stayMessage }));
        }
        throw cause;
      }
    });
  };

  if (!block) return <section className={styles.editor} aria-label={between ? '경유지 추가' : '장소 추가'}>
    <h2>{between ? '경유지 추가' : '장소 추가'}</h2>
    <form onSubmit={async (event) => {
      event.preventDefault();
      if (!query.trim()) return;
      setSearching(true);
      setSearched(false);
      setSearchError(null);
      setResults([]);
      setStays({});
      setStayErrors({});
      setAskStay(new Set());
      try {
        setResults((await placesApi.search({ q: query.trim() })).places);
        setSearched(true);
      } catch (cause) {
        setSearchError(toApiError(cause).message);
      } finally {
        setSearching(false);
      }
    }}>
      <label>장소 검색 <input required value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <Button type="submit" disabled={disabled || searching}>검색</Button>
    </form>
    {searchError && <p role="alert" className={styles.message}>{searchError}</p>}
    {searched && results.length === 0 && <p className={styles.message}>검색 결과가 없습니다.</p>}
    {results.length > 0 && <ul className={styles.results}>{results.map((place) => <li key={place.kakaoPlaceId}>
      <span><span className={styles.resultName}>{place.name}</span>{place.address && <span className={styles.resultAddress}>{place.address}</span>}</span>
      <span className={styles.resultActions}>
        {needsStay(place) && <select
          className={styles.stayField}
          aria-label={`${place.name} 머무를 시간`}
          aria-invalid={Boolean(stayErrors[place.kakaoPlaceId])}
          value={stays[place.kakaoPlaceId] ?? ''}
          onChange={(event) => {
            const value = Number(event.target.value);
            const key = place.kakaoPlaceId;
            setStays((prev) => { const next = { ...prev }; if (value) next[key] = value; else delete next[key]; return next; });
            if (value) setStayErrors((prev) => { const next = { ...prev }; delete next[key]; return next; });
          }}
        >
          <option value="">머무를 시간</option>
          {STAY_OPTIONS.map((minutes) => <option key={minutes} value={minutes}>{formatDuration(minutes)}</option>)}
        </select>}
        <Button disabled={disabled} onClick={() => addPlace(place)}>추가</Button>
      </span>
      {stayErrors[place.kakaoPlaceId] && <p role="alert" className={styles.stayError}>{stayErrors[place.kakaoPlaceId]}</p>}
    </li>)}</ul>}
  </section>;

  return <div className={`${styles.editor} ${styles.inCard}`} aria-label="이 장소 고치기">
    <h3>이 장소 고치기</h3>
    <form onSubmit={(event) => { event.preventDefault(); void onChange(() => tripsApi.updateBlock(tripId, block.id, { stayMin: Number(stayMin) })); }}>
      <label>체류시간(분) <input type="number" min="1" required value={stayMin} onChange={(event) => setStayMin(Number(event.target.value))} /></label>
      <Button type="submit" variant="outline" disabled={disabled}>체류시간 변경</Button>
    </form>
    {block.isFixed
      // 고정 장소는 순서·시각이 바뀌지 않는다(원칙 1). 순서 입력을 두지 않는다.
      ? <p className={styles.note}>고정한 장소라 순서와 시각은 바뀌지 않아요.</p>
      : <form onSubmit={(event) => { event.preventDefault(); void onChange(() => tripsApi.updateBlock(tripId, block.id, { seq: Number(seq) })); }}>
        <label>순서 <input type="number" min="1" required value={seq} onChange={(event) => setSeq(Number(event.target.value))} /></label>
        <Button type="submit" variant="outline" disabled={disabled}>순서 변경</Button>
      </form>}
    {confirmRemove
      // 확인 단계: 같은 자리에는 '취소'가 와서 빠른 두 번 누르기로 바로 지워지지 않는다.
      ? <div className={styles.confirm} role="group" aria-label="고정 장소 빼기 확인">
        <p role="status" className={styles.note}>고정한 시각도 함께 사라져요. 정말 뺄까요?</p>
        <Button ref={cancelRef} variant="outline" disabled={disabled} onClick={() => setConfirmRemove(false)}>취소</Button>
        <Button variant="ghost" className={styles.danger} disabled={disabled} onClick={() => onChange(() => tripsApi.deleteBlock(tripId, block.id))}>고정 장소지만 빼기</Button>
      </div>
      : <Button variant="ghost" className={styles.danger} disabled={disabled} onClick={() => (block.isFixed ? setConfirmRemove(true) : onChange(() => tripsApi.deleteBlock(tripId, block.id)))}>일정에서 빼기</Button>}
  </div>;
}
