import { useState } from 'react';
import { placesApi, rememberKakaoPlace, toApiError, tripsApi } from '@/api';
import { Button } from '@/components';
import type { Block, PlaceSearchItem, Schedule } from '@/types/api';
import styles from './BlockEditor.module.css';

type Change = (action: () => Promise<{ schedule: Schedule }>) => Promise<void>;

export function BlockEditor({ tripId, block, between, disabled, onChange }: {
  tripId: string;
  block?: Block;
  between?: { fromBlockId: string; toBlockId: string };
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

  if (!block) return <section className={styles.editor} aria-label={between ? '경유지 추가' : '장소 추가'}>
    <h2>{between ? '경유지 추가' : '장소 추가'}</h2>
    <form onSubmit={async (event) => {
      event.preventDefault();
      if (!query.trim()) return;
      setSearching(true);
      setSearched(false);
      setSearchError(null);
      setResults([]);
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
    {searchError && <p role="alert">{searchError}</p>}
    {searched && results.length === 0 && <p>검색 결과가 없습니다.</p>}
    {results.length > 0 && <ul className={styles.results}>{results.map((place) => <li key={place.kakaoPlaceId}>
      <span>{place.name}{place.address ? ` · ${place.address}` : ''}</span>
      <Button disabled={disabled} onClick={() => {
        if (!place.placeId) rememberKakaoPlace(place.kakaoPlaceId, { name: place.name, coords: place.coords });
        void onChange(() => tripsApi.addBlock(tripId, {
          place: place.placeId ? { placeId: place.placeId } : { kakaoPlaceId: place.kakaoPlaceId, placeUrl: place.placeUrl },
          isFixed: false, origin: 'USER', ...between,
        }));
      }}>추가</Button>
    </li>)}</ul>}
  </section>;

  return <div className={styles.editor} aria-label="블록 편집">
    <h3>블록 편집</h3>
    <form onSubmit={(event) => { event.preventDefault(); void onChange(() => tripsApi.updateBlock(tripId, block.id, { stayMin: Number(stayMin) })); }}>
      <label>체류시간(분) <input type="number" min="1" required value={stayMin} onChange={(event) => setStayMin(Number(event.target.value))} /></label>
      <Button type="submit" disabled={disabled}>체류시간 변경</Button>
    </form>
    <form onSubmit={(event) => { event.preventDefault(); void onChange(() => tripsApi.updateBlock(tripId, block.id, { seq: Number(seq) })); }}>
      <label>순서 <input type="number" min="1" required value={seq} onChange={(event) => setSeq(Number(event.target.value))} /></label>
      <Button type="submit" disabled={disabled}>순서 변경</Button>
    </form>
    <Button variant="outline" disabled={disabled} onClick={() => onChange(() => tripsApi.deleteBlock(tripId, block.id))}>블록 삭제</Button>
  </div>;
}
