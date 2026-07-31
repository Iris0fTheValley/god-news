import {useEffect, useRef, type ReactNode} from 'react';

interface ModalDialogProps {
  open: boolean;
  className: string;
  labelledBy: string;
  onClose: () => void;
  children: ReactNode;
}

/**
 * One modal boundary for every drawer and confirmation flow.
 *
 * Native showModal() supplies focus containment and makes the rest of the
 * application inert.  Feature pages own the content and close decision.
 */
export function ModalDialog({
  open,
  className,
  labelledBy,
  onClose,
  children,
}: ModalDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (dialog === null) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={className}
      aria-labelledby={labelledBy}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      {children}
    </dialog>
  );
}
