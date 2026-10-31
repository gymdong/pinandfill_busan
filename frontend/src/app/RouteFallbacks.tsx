import { useNavigate } from 'react-router-dom';
import { Button, EmptyState, ErrorState } from '@/components';
import { paths } from './paths';

export function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <EmptyState
      title="페이지를 찾을 수 없어요"
      action={<Button onClick={() => navigate(paths.tripStart())}>처음으로</Button>}
    />
  );
}

export function RouteErrorPage() {
  return <ErrorState message="화면을 여는 중 문제가 생겼어요." onRetry={() => window.location.reload()} />;
}
