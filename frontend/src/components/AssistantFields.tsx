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
