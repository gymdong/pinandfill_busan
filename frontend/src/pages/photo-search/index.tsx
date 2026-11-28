import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { placesApi, toApiError } from '@/api';
import { paths } from '@/app/paths';
import { Banner, Button, LoadingState } from '@/components';
import { PINNED_LIMIT, PINNED_LIMIT_MESSAGE, pinnedKey, useTripDraft, type PinnedPlace } from '@/store/tripDraft';
import type { PhotoSearchResponse, PlaceSummary } from '@/types/api';
import { shrinkPhoto } from '@/utils/image';
import mood from '@/pages/mood-search/MoodSearchPage.module.css';
import styles from './PhotoSearchPage.module.css';

type State =
  | { status: 'idle' }
  | { status: 'searching' }
  | { status: 'done'; result: PhotoSearchResponse }
  | { status: 'error'; message: string };

function toPinned(place: PlaceSummary): PinnedPlace {
  return { kind: 'PUBLIC', placeId: place.id, name: place.name, coords: { lat: place.lat, lng: place.lng } };
}

/**
 * UI 사진으로 찾기(FR-012, UC-008). 사진은 줄이고 위치 정보를 지운 뒤 보내며, 서버도 저장하지 않는다.
 * 후보는 공공 DB 장소에서만 최대 3곳이고, 확신이 낮으면 이름 검색으로 안내한다.
 */
export default function PhotoSearchPage() {
  const navigate = useNavigate();
  const { pinned, addPinned, removePinned } = useTripDraft();
  const [state, setState] = useState<State>({ status: 'idle' });
  const [preview, setPreview] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const full = pinned.length >= PINNED_LIMIT;

  // 화면을 떠나면 진행 중인 요청을 취소한다.
  useEffect(() => () => controller.current?.abort(), []);
  // 미리보기를 바꾸거나 떠나면 이전 미리보기 주소를 해제한다(진행 중인 요청은 건드리지 않는다).
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  async function pick(file: File | undefined) {
    if (!file) return;
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setPreview(URL.createObjectURL(file));
    setState({ status: 'searching' });
    let upload: File;
    try {
      upload = await shrinkPhoto(file);
    } catch {
      setState({ status: 'error', message: '이 사진은 읽을 수 없어요. JPG·PNG 사진으로 다시 골라 주세요.' });
      return;
    }
    try {
      const result = await placesApi.photoSearch(upload, { signal: current.signal });
      if (!current.signal.aborted) setState({ status: 'done', result });
    } catch (cause) {
      if (!current.signal.aborted) setState({ status: 'error', message: toApiError(cause).message });
    }
  }

  const togglePin = (place: PlaceSummary) => {
    const entry = toPinned(place);
    if (pinned.some((item) => pinnedKey(item) === pinnedKey(entry))) removePinned(pinnedKey(entry));
    else addPinned(entry);
  };

  return (
    <main className={mood.page}>
      <header className={mood.header}>
        <button type="button" className={mood.back} aria-label="뒤로 가기" onClick={() => navigate(paths.tripStart())}>
          <span aria-hidden="true">‹</span>
        </button>
        <h1 className={mood.title}>사진으로 찾기</h1>
      </header>

      <label className={styles.picker}>
        <input
          type="file" accept="image/jpeg,image/png,image/webp" className="sr-only"
          disabled={state.status === 'searching'}
          onChange={(event) => { void pick(event.target.files?.[0]); event.target.value = ''; }}
        />
        {preview
          ? <img className={styles.preview} src={preview} alt="고른 사진" />
          : <span className={styles.placeholder}>가고 싶은 곳의 사진을 골라 주세요</span>}
        <span className={styles.pickLabel}>{preview ? '다른 사진 고르기' : '사진 고르기'}</span>
      </label>
      <p className={styles.privacy}>사진은 장소를 찾는 데만 쓰고 저장하지 않아요. 보내기 전에 촬영 위치 정보를 지워요.</p>

      {state.status === 'searching' && <LoadingState message="사진 속 장소를 찾는 중이에요" />}
      {state.status === 'error' && <Banner tone="warn" title="사진으로 찾지 못했어요">{state.message}</Banner>}
      {state.status === 'done' && state.result.notFound && (
        <Banner tone="warn" title="사진으로는 찾지 못했어요">
          특징이나 장소 이름을 알면 여행 시작 화면에서 검색해 담을 수 있어요.
        </Banner>
      )}

      {state.status === 'done' && !state.result.notFound && (
        <>
          {full && <Banner>{PINNED_LIMIT_MESSAGE}</Banner>}
          <ul className={mood.results} aria-label="사진 속 장소 후보">
            {state.result.candidates.map(({ place, confidence }) => {
              const isPinned = pinned.some((entry) => pinnedKey(entry) === pinnedKey(toPinned(place)));
              return (
                <li key={place.id} className={mood.card}>
                  <div className={mood.body}>
                    <div className={mood.info}>
                      <h2 className={mood.name}>{place.name}</h2>
                      <p className={mood.evidence}>확신도 {Math.round(confidence * 100)}% · {place.category}</p>
                      <p className={mood.evidenceSource}>공공 데이터 · 기준일 {place.refDate ?? '확인 필요'}</p>
                    </div>
                    <Button
                      variant={isPinned ? 'outline' : 'accent'} aria-pressed={isPinned}
                      aria-label={`${place.name} ${isPinned ? '빼기' : '담기'}`}
                      disabled={!isPinned && full} onClick={() => togglePin(place)}
                    >
                      {isPinned ? '✓ 담김' : '담기'}
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}

      <footer className={mood.footer}>
        <p className={mood.footerNote}>공공 DB에 있는 장소에서만 골랐어요 · 확신도는 AI가 판단한 값이에요</p>
        <Button block onClick={() => navigate(paths.tripStart())}>돌아가기</Button>
      </footer>
    </main>
  );
}
