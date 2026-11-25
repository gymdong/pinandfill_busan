import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { placesApi, toApiError, type ApiError } from '@/api';
import { Badge, Button, LoadingState } from '@/components';
import { pinnedKey } from '@/store/tripDraft';
import type { PlaceSearchItem } from '@/types/api';
import { toPinnedPlace } from './pinned';
import styles from './PlaceSearch.module.css';

type SearchState =
  | { status: 'idle' }
  | { status: 'loading'; query: string }
  | { status: 'success'; query: string; places: PlaceSearchItem[] }
  | { status: 'error'; query: string; error: ApiError };

export interface PlaceSearchProps {
  /** 이미 담은 장소의 `pinnedKey`. 담긴 결과는 '담김'으로 표시한다. */
  pickedKeys: ReadonlySet<string>;
  onPick: (item: PlaceSearchItem) => void;
  /** 담긴 결과를 다시 눌렀을 때. 없으면 담긴 결과는 누를 수 없다. */
  onUnpick?: (item: PlaceSearchItem) => void;
  /** 결과가 없거나 검색이 안 될 때 함께 보여 줄 다른 방법 안내(예: 지도에서 고르기) */
  fallbackHint?: ReactNode;
  /** 더 담을 수 없을 때의 안내. 있으면 담기지 않은 결과는 누를 수 없다(꼭 갈 곳 상한). */
  pickBlocked?: string | null;
}

/** 이름에서 검색어와 겹치는 부분을 굵게 표시한다. */
function highlight(name: string, query: string): ReactNode {
  const index = query ? name.toLowerCase().indexOf(query.toLowerCase()) : -1;
  if (index < 0) return name;
  return (
    <>
      {name.slice(0, index)}
      <mark className={styles.match}>{name.slice(index, index + query.length)}</mark>
      {name.slice(index + query.length)}
    </>
  );
}

/**
 * 장소 검색(API-003)과 결과 배지(FR-001).
 * 카카오 응답은 화면에 보여 주기만 하고 저장하지 않는다. 검색은 입력할 때마다가 아니라 제출할 때 한 번 호출한다.
 */
export function PlaceSearch({ pickedKeys, onPick, onUnpick, fallbackHint, pickBlocked }: PlaceSearchProps) {
  const inputId = useId();
  const [text, setText] = useState('');
  const [state, setState] = useState<SearchState>({ status: 'idle' });
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  function search(query: string) {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setState({ status: 'loading', query });
    placesApi.search({ q: query }, { signal: current.signal }).then(
      ({ places }) => {
        if (!current.signal.aborted) setState({ status: 'success', query, places });
      },
      (error: unknown) => {
        if (!current.signal.aborted) setState({ status: 'error', query, error: toApiError(error) });
      },
    );
  }

  /** 결과·안내를 닫고 처음 상태로 돌아간다. 진행 중인 검색도 멈춘다. */
  function close() {
    controller.current?.abort();
    setState({ status: 'idle' });
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const query = text.trim();
    if (query) search(query);
  }

  return (
    <div className={styles.search}>
      <form role="search" className={styles.form} onSubmit={submit}>
        <label htmlFor={inputId} className="sr-only">장소 검색</label>
        <input
          id={inputId}
          className={styles.input}
          type="search"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            // 검색어를 모두 지우면(입력창의 지우기 버튼 포함) 결과도 닫는다.
            if (!event.target.value.trim()) close();
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape' && state.status !== 'idle') close();
          }}
          placeholder="장소 이름으로 찾기"
          autoComplete="off"
          enterKeyHint="search"
        />
        <Button type="submit" variant="outline" disabled={!text.trim()} loading={state.status === 'loading'}>검색</Button>
      </form>

      {state.status !== 'idle' && (
        <div className={styles.resultsBar}>
          <span className={styles.meta}>
            {state.status === 'success' ? `‘${state.query}’ 검색 결과 ${state.places.length}곳` : `‘${state.query}’ 검색`}
          </span>
          <button type="button" className={styles.close} onClick={close}>
            결과 닫기
          </button>
        </div>
      )}

      {state.status === 'loading' && <LoadingState message="장소를 찾는 중이에요" />}

      {state.status === 'error' && (
        <div className={styles.notice} role="alert">
          <p>{state.error.message}</p>
          {fallbackHint ? <p className={styles.hint}>{fallbackHint}</p> : null}
          <Button variant="outline" onClick={() => search(state.query)}>다시 검색</Button>
        </div>
      )}

      {state.status === 'success' && state.places.length === 0 && (
        <div className={styles.notice} role="status">
          <p>‘{state.query}’ 검색 결과가 없어요.</p>
          {fallbackHint ? <p className={styles.hint}>{fallbackHint}</p> : null}
        </div>
      )}

      {state.status === 'success' && state.places.length > 0 && (
        <>
          {pickBlocked ? <p className={styles.hint} role="status">{pickBlocked}</p> : null}
          <ul className={styles.results} aria-label="검색 결과">
            {state.places.map((item) => {
              const picked = pickedKeys.has(pinnedKey(toPinnedPlace(item)));
              const meta = [item.category, item.address].filter(Boolean).join(' · ');
              return (
                <li key={item.kakaoPlaceId}>
                  <button
                    type="button"
                    className={styles.result}
                    aria-pressed={picked}
                    disabled={picked ? !onUnpick : Boolean(pickBlocked)}
                    onClick={() => (picked ? onUnpick?.(item) : onPick(item))}
                  >
                    <span className={styles.resultText}>
                      <span className={styles.name}>{highlight(item.name, state.query)}</span>
                      {meta ? <span className={styles.meta}>{meta}</span> : null}
                      <span className={styles.badges}>
                        <Badge kind={item.badge === 'DETAIL' ? 'detail' : 'basic'} />
                        {item.hoursStatus === 'NEEDS_CHECK' ? <Badge kind="needsCheck" label="영업시간 확인 필요" /> : null}
                      </span>
                    </span>
                    <span className={picked ? styles.picked : styles.pick}>{picked ? '✓ 담김' : '담기'}</span>
                  </button>
                </li>
              );
            })}
          </ul>
          {fallbackHint ? <p className={styles.hint}>{fallbackHint}</p> : null}
        </>
      )}
    </div>
  );
}
