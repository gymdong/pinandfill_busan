import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Badge,
  Banner,
  BottomSheet,
  Button,
  Chip,
  EmptyState,
  ErrorState,
  LoadingState,
  useToast,
} from '@/components';
import { CrowdBadge } from '@/features/crowd';
import { paths } from './paths';
import styles from './DevGallery.module.css';

const SAMPLE_ID = '00000000-0000-4000-8000-000000000001';

/** 개발 서버 전용(`/__dev`). 공통 컴포넌트를 360px에서 눈으로 점검한다. */
export default function DevGallery() {
  const [sheetOpen, setSheetOpen] = useState(false);
  const [chipSelected, setChipSelected] = useState(true);
  const { showToast } = useToast();

  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>공통 컴포넌트</h1>

      <section className={styles.section}>
        <h2>화면 경로</h2>
        <nav className={styles.links}>
          <Link to={paths.tripStart()}>UI-01 여행 시작</Link>
          <Link to={paths.timeline(SAMPLE_ID)}>UI-02 타임라인</Link>
          <Link to={paths.placeDetail(SAMPLE_ID)}>UI-04 장소 상세</Link>
          <Link to={paths.mapView(SAMPLE_ID)}>UI-06 지도</Link>
          <Link to={paths.moodSearch()}>UI-08 분위기로 찾기</Link>
          <Link to={paths.admin()}>UI-09 관리자</Link>
          <Link to={paths.photoSearch()}>UI-07 사진으로 찾기 (P1)</Link>
          <Link to={paths.sharedTrip('sample')}>공유 열람 (P1)</Link>
        </nav>
      </section>

      <section className={styles.section}>
        <h2>버튼</h2>
        <div className={styles.row}>
          <Button>primary</Button>
          <Button variant="accent">accent</Button>
          <Button variant="outline">outline</Button>
          <Button variant="ghost">ghost</Button>
          <Button loading>loading</Button>
        </div>
        <Button block>코스 만들기</Button>
      </section>

      <section className={styles.section}>
        <h2>칩</h2>
        <div className={styles.row}>
          <Chip selected={chipSelected} onClick={() => setChipSelected((value) => !value)}>
            바다 전망
          </Chip>
          <Chip>골목·산책</Chip>
          <Chip dashed>+ 태그</Chip>
        </div>
      </section>

      <section className={styles.section}>
        <h2>배지</h2>
        <div className={styles.row}>
          <Badge kind="detail" />
          <Badge kind="basic" />
          <Badge kind="needsCheck" />
          <Badge kind="needsCheck" label="영업시간 확인 필요" />
          <Badge kind="estimated" />
          <Badge kind="expected" />
        </div>
      </section>

      <section className={styles.section}>
        <h2>혼잡 배지</h2>
        <div className={styles.row}>
          <CrowdBadge grade="여유" />
          <CrowdBadge grade="보통" confidence="중간" />
          <CrowdBadge grade="붐빔" hourLabel="18시" />
          <CrowdBadge grade="매우 붐빔" confidence="높음" />
          <CrowdBadge grade={null} />
        </div>
      </section>

      <section className={styles.section}>
        <h2>배너·토스트·시트</h2>
        <Banner title="태종대 13:30 – 15:00 · 예상 붐빔" tone="warn">
          평소보다 사람이 많을 것으로 보여요.
        </Banner>
        <Banner action={<Button variant="accent">순서 바꿔보기</Button>}>16:00 이후가 한 단계 여유로워요</Banner>
        <div className={styles.row}>
          <Button variant="outline" onClick={() => showToast('꼭 갈 곳에 담았어요')}>
            토스트
          </Button>
          <Button variant="outline" onClick={() => setSheetOpen(true)}>
            바텀 시트
          </Button>
        </div>
        <BottomSheet
          open={sheetOpen}
          onClose={() => setSheetOpen(false)}
          title="가는 길에 들를 곳"
          description="감천문화마을 → 태종대"
          footer={<Button block>코스에 추가</Button>}
        >
          <p>시트 내용</p>
        </BottomSheet>
      </section>

      <section className={styles.section}>
        <h2>상태 화면</h2>
        <LoadingState />
        <EmptyState title="어울리는 곳을 찾지 못했어요" description="태그를 직접 골라 보세요" />
        <ErrorState message="장소 검색에 실패했어요." onRetry={() => showToast('다시 시도')} />
      </section>
    </main>
  );
}
