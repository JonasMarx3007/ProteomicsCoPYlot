import type { InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes, ReactNode } from "react";
import { useAssistantControl, useAssistantSurface, AssistantControlScope, useAssistantCanvasButton } from "../lib/assistantControls";

export function AssistantCanvasButton({ effect, onClick, ...props }: Omit<import("react").ButtonHTMLAttributes<HTMLButtonElement>, "onClick"> & { effect: "add" | "remove"; onClick: () => void }) {
  const ref = useAssistantCanvasButton(onClick, effect);
  return <button {...props} onClick={onClick} ref={ref} />;
}

export function AssistantSurface({ module, enabled, children }: { module: string; enabled: boolean; children: ReactNode }) {
  useAssistantSurface(module);
  return <AssistantControlScope.Provider value={enabled}>{children}</AssistantControlScope.Provider>;
}

// Advanced plot mode is the user's switch: it decides whether the appearance
// panel is on screen, never whether the assistant may restyle a plot. When the
// user keeps it off the panel is still mounted offscreen and inert, so its
// settings register as assistant controls and a styling request applies exactly
// as it would with the panel open — the assistant never flips the toggle.
export function AssistantAppearanceMount({ visible, children }: { visible: boolean; children: ReactNode }) {
  if (visible) return <>{children}</>;
  return (
    <div data-assistant-offscreen="true" aria-hidden="true" inert
         className="pointer-events-none fixed left-[-10000px] top-0 h-px w-px overflow-hidden">
      {children}
    </div>
  );
}

export function AssistantInput(props: InputHTMLAttributes<HTMLInputElement>) {
  const ref = useAssistantControl(props.onChange, props.onBlur);
  return <input {...props} ref={ref} />;
}

export function AssistantSelect(props: SelectHTMLAttributes<HTMLSelectElement>) {
  const ref = useAssistantControl(props.onChange, props.onBlur);
  return <select {...props} ref={ref} />;
}

export function AssistantTextarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ref = useAssistantControl(props.onChange, props.onBlur);
  return <textarea {...props} ref={ref} />;
}
