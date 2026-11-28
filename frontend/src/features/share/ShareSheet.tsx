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
  | { status: 'ready'; url: string }
  | { status: 'error'; message: string };

/**
 * FR-011 읽기 전용 공유 링크(API-019). 시트를 열면 링크를 하나 만든다.
 * 받은 사람은 일정을 볼 수만 있다. 링크에는 여행 ID 가 없다.
 */
export function ShareSheet({ tripId, onClose }: ShareSheetProps) {
  const [state, setState] = useState<State>({ status: 'creating' });
  const [copied, setCopied] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    tripsApi.share(tripId, {}, { signal: controller.signal })
      .then((result) => setState({ status: 'ready', url: new URL(result.url, window.location.origin).toString() }))
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setState({ status: 'error', message: toApiError(cause).message });
      });
    return () => controller.abort();
  }, [tripId, attempt]);

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      // 복사 권한이 없으면 주소를 선택해 두어 직접 복사하게 한다.
      input.current?.select();
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
      <p role="status" className={styles.hint}>{copied ? '링크를 복사했어요. 동행자에게 붙여 보내 주세요.' : ''}</p>
    </div>}
  </BottomSheet>;
}
