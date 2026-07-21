import type { InputHTMLAttributes } from "react";
import { useState } from "react";

type PasswordFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type">;

export default function PasswordField({ className = "", disabled, ...props }: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);
  const buttonLabel = visible ? "Hide password" : "Show password";

  return (
    <div className="relative">
      <input
        {...props}
        disabled={disabled}
        type={visible ? "text" : "password"}
        className={`${className} pr-11`}
      />
      <button
        type="button"
        aria-label={buttonLabel}
        title={buttonLabel}
        disabled={disabled}
        onClick={() => setVisible((current) => !current)}
        className="absolute inset-y-0 right-2 flex w-8 items-center justify-center rounded-md text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-400 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {visible ? (
          <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 3l18 18" />
            <path d="M10.6 10.6a2 2 0 0 0 2.8 2.8" />
            <path d="M9.9 4.2A9.4 9.4 0 0 1 12 4c6.5 0 10 8 10 8a17 17 0 0 1-2.2 3.2" />
            <path d="M6.5 6.5C3.7 8.1 2 12 2 12s3.5 8 10 8a9.7 9.7 0 0 0 4.1-.9" />
          </svg>
        ) : (
          <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M2 12s3.5-8 10-8 10 8 10 8-3.5 8-10 8S2 12 2 12z" />
            <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />
          </svg>
        )}
      </button>
    </div>
  );
}
