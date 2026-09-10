import { useEffect, useRef, type ReactNode } from "react";

/** Native modal semantics keep background controls inert and contain keyboard focus. */
export default function Modal({ children, onClose, labelledBy, busy = false, className = "" }: {
  children: ReactNode; onClose: () => void; labelledBy: string; busy?: boolean; className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    const trigger = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    dialog?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      dialog?.close();
      document.body.style.overflow = previousOverflow;
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
    };
  }, []);
  return <dialog ref={ref} aria-labelledby={labelledBy} aria-modal="true"
    className={`copylot-modal ${className}`}
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    {children}
  </dialog>;
}
