import { forwardRef, type ButtonHTMLAttributes } from 'react';
import styles from './Button.module.css';

export type ButtonVariant = 'primary' | 'accent' | 'outline' | 'ghost';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  /** 부모 폭을 꽉 채운다(하단 고정 버튼 등). */
  block?: boolean;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', block = false, loading = false, disabled, className, children, type = 'button', ...rest },
  ref,
) {
  const classes = [styles.button, styles[variant], block ? styles.block : '', className ?? '']
    .filter(Boolean)
    .join(' ');
  return (
    <button ref={ref} type={type} className={classes} disabled={disabled || loading} aria-busy={loading} {...rest}>
      {children}
    </button>
  );
});
