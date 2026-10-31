import { EmptyState } from '@/components';

interface PagePlaceholderProps {
  screen: string;
  owner: string;
  requirements: string;
  /** P1 화면은 P0 검증 후 배분되므로 비활성으로 표시한다. */
  disabled?: boolean;
}

/** 각 담당이 페이지를 구현하면서 지우는 임시 자리표시. */
export function PagePlaceholder({ screen, owner, requirements, disabled = false }: PagePlaceholderProps) {
  return (
    <main>
      <EmptyState
        title={screen}
        description={
          disabled
            ? `P1 화면이에요. P0 검증(11/22)이 끝난 뒤 배분해요. (${requirements})`
            : `담당 ${owner} · ${requirements}`
        }
      />
    </main>
  );
}
