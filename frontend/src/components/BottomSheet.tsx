import { useEffect, useRef, type MouseEvent, type ReactNode } from 'react';
import styles from './BottomSheet.module.css';

export interface BottomSheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  /** 하단에 고정되는 버튼 영역 */
  footer?: ReactNode;
}

/** 네이티브 dialog로 포커스 가두기와 Esc 닫기를 처리한다. */
export function BottomSheet({ open, onClose, title, description, children, footer }: BottomSheetProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  const handleBackdropClick = (event: MouseEvent<HTMLDialogElement>) => {
    if (event.target === dialogRef.current) onClose();
  };

  return (
    <dialog
      ref={dialogRef}
      className={styles.sheet}
      aria-label={title}
      onClick={handleBackdropClick}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className={styles.panel}>
        <div className={styles.handle} aria-hidden="true" />
        <header className={styles.header}>
          <div>
            {/* 열릴 때 포커스를 제목에 둔다(화면 읽기가 제목부터 읽고, 닫기 버튼에 포커스 테두리가 뜨지 않게). */}
            <h2 className={styles.title} tabIndex={-1} autoFocus>{title}</h2>
            {description ? <p className={styles.description}>{description}</p> : null}
          </div>
          <button type="button" className={styles.close} aria-label="닫기" onClick={onClose}>
            ✕
          </button>
        </header>
        <div className={styles.body}>{children}</div>
        {footer ? <footer className={styles.footer}>{footer}</footer> : null}
      </div>
    </dialog>
  );
}
