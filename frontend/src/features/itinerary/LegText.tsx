import { useId, useState } from 'react';
import type { Leg } from '@/types/api';
import { modeLabel } from './format';
import styles from './LegText.module.css';

/**
 * 구간 표시. 추정(ESTIMATED) 구간은 시간 앞에 작은 '≈'를 두고, 누르면 바로 아래에 설명이 펼쳐진다
 * (시트 안에서 잘리지 않게 겹치는 툴팁 대신 인라인 문구). 화면 읽기 프로그램에는 '(추정)'으로 읽힌다.
 * 이동시간이 없으면 추정 표시 없이 '이동시간 확인 필요'다.
 */
export function LegText({ leg }: { leg: Leg }) {
  const [open, setOpen] = useState(false);
  const noteId = useId();
  const prefix = `${modeLabel(leg.mode)} · `;
  if (leg.durationMin === null) return <>{prefix}이동시간 확인 필요</>;
  if (leg.source !== 'ESTIMATED') return <>{prefix}{leg.durationMin}분</>;
  return (
    <>
      {prefix}
      <button
        type="button"
        className={styles.estimate}
        aria-label={`${leg.durationMin}분 (추정)`}
        aria-expanded={open}
        aria-controls={noteId}
        onClick={() => setOpen((value) => !value)}
      >
        <span aria-hidden="true">≈</span>
        {leg.durationMin}분
      </button>
      {open ? (
        <span id={noteId} className={styles.note}>
          추정 이동시간이에요. 경로 API 결과가 없어 직선거리로 계산했어요.
        </span>
      ) : null}
    </>
  );
}
