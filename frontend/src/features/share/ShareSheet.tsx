import { useEffect, useRef, useState } from 'react';
import { toApiError, tripsApi } from '@/api';
import { BottomSheet, Button } from '@/components';
import styles from './ShareSheet.module.css';

export interface ShareSheetProps {
  tripId: string;
  onClose: () => void;
}

type State =
  | { status: 'creating' }
  | { status: 'ready'; url: string; expiresAt: string | null }
  | { status: 'error'; message: string };

/** 같은 탭에서 시트를 다시 열면 만든 링크를 다시 쓴다(열 때마다 새 링크가 쌓이지 않게). */
const cacheKey = (tripId: string) => `pinandfill:share:${tripId}`;
function cached(tripId: string): { url: string; expiresAt: string | null } | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(cacheKey(tripId)) ?? 'null') as { url?: unknown; expiresAt?: unknown } | null;
    if (typeof value?.url !== 'string') return null;
    const expiresAt = typeof value.expiresAt === 'string' ? value.expiresAt : null;
    // 만료 1시간 전부터는 새로 만든다.
    if (expiresAt && Date.parse(expiresAt) - Date.now() < 3_600_000) return null;
    return { url: value.url, expiresAt };
  } catch {
    return null;
  }
}
function remember(tripId: string, value: { url: string; expiresAt: string | null }) {
  try { sessionStorage.setItem(cacheKey(tripId), JSON.stringify(value)); } catch { /* 저장 불가: 다음에 새로 만든다 */ }
}
function untilLabel(expiresAt: string | null): string {
  if (!expiresAt) return '';
  const date = new Date(expiresAt);
  if (Number.isNaN(date.getTime())) return '';
  return `${new Intl.DateTimeFormat('ko-KR', { month: 'long', day: 'numeric', timeZone: 'Asia/Seoul' }).format(date)}까지 열려요.`;
}

/**
 * FR-011 읽기 전용 공유 링크(API-019). 시트를 열면 링크를 하나 만든다.
 * 받은 사람은 일정을 볼 수만 있다. 링크에는 여행 ID 가 없다.
 */
export function ShareSheet({ tripId, onClose }: ShareSheetProps) {
  const [state, setState] = useState<State>(() => {
    const hit = cached(tripId);
    return hit ? { status: 'ready', ...hit } : { status: 'creating' };
  });
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  const creating = state.status === 'creating';
  useEffect(() => {
    if (!creating) return undefined;
    const controller = new AbortController();
    tripsApi.share(tripId, {}, { signal: controller.signal })
      .then((result) => {
        const link = { url: new URL(result.url, window.location.origin).toString(), expiresAt: result.expiresAt ?? null };
        remember(tripId, link);
        setState({ status: 'ready', ...link });
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setState({ status: 'error', message: toApiError(cause).message });
      });
    return () => controller.abort();
  }, [tripId, attempt, creating]);

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setCopyFailed(false);
    } catch {
      // 복사 권한이 없으면(HTTP 접속 등) 주소를 선택해 두고 직접 복사하도록 안내한다.
      input.current?.focus();
      input.current?.setSelectionRange(0, url.length);
      setCopyFailed(true);
    }
  }

  const canShare = typeof navigator.share === 'function';

  return <BottomSheet open onClose={onClose} title="일정 공유" description="링크를 받은 사람은 일정을 볼 수만 있어요. 고치거나 되돌릴 수는 없어요.">
    {state.status === 'creating' && <p role="status" className={styles.status}>공유 링크를 만드는 중…</p>}
    {state.status === 'error' && <div role="alert" className={styles.status}>
      <p>공유 링크를 만들지 못했어요. {state.message}</p>
      <Button variant="outline" onClick={() => { setState({ status: 'creating' }); setAttempt(attempt + 1); }}>다시 시도</Button>
    </div>}
    {state.status === 'ready' && <div className={styles.ready}>
      <label className={styles.label} htmlFor="share-url">공유 링크</label>
      <input ref={input} id="share-url" className={styles.url} value={state.url} readOnly onFocus={(event) => event.currentTarget.select()} />
      <div className={styles.actions}>
        <Button onClick={() => { void copy(state.url); }}>{copied ? '복사했어요' : '링크 복사'}</Button>
        {canShare && <Button variant="outline" onClick={() => { void navigator.share({ title: '핀앤필 부산 일정', url: state.url }).catch(() => undefined); }}>다른 앱으로 보내기</Button>}
      </div>
      <p role="status" className={styles.hint}>
        {copied ? '링크를 복사했어요. 동행자에게 붙여 보내 주세요.' : copyFailed ? '자동 복사가 안 돼요. 위 주소를 길게 눌러 복사해 주세요.' : ''}
      </p>
      {untilLabel(state.expiresAt) && <p className={styles.hint}>{untilLabel(state.expiresAt)}</p>}
    </div>}
  </BottomSheet>;
}
