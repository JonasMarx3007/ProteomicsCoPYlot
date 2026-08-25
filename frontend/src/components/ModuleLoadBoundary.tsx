import { Component, type ErrorInfo, type ReactNode } from "react";

type ModuleLoadBoundaryProps = {
  children: ReactNode;
  onReturnToUpload: () => void;
};

type ModuleLoadBoundaryState = {
  failed: boolean;
};

export default class ModuleLoadBoundary extends Component<
  ModuleLoadBoundaryProps,
  ModuleLoadBoundaryState
> {
  state: ModuleLoadBoundaryState = { failed: false };

  static getDerivedStateFromError(): ModuleLoadBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Failed to render a lazily loaded module", error, info);
  }

  render() {
    if (!this.state.failed) return this.props.children;

    return (
      <div
        className="rounded-2xl border border-amber-200 bg-amber-50 p-8 text-center shadow-sm"
        role="alert"
      >
        <div className="text-lg font-semibold text-amber-950">
          This module could not be loaded
        </div>
        <p className="mx-auto mt-2 max-w-xl text-sm text-amber-900">
          The application may have been updated, or the connection may have been interrupted.
          Reloading fetches the current module files safely.
        </p>
        <div className="mt-5 flex flex-wrap justify-center gap-3">
          <button
            type="button"
            className="rounded-lg bg-amber-900 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-800"
            onClick={() => window.location.reload()}
          >
            Reload and retry
          </button>
          <button
            type="button"
            className="rounded-lg border border-amber-300 bg-white px-4 py-2 text-sm font-semibold text-amber-950 hover:bg-amber-100"
            onClick={this.props.onReturnToUpload}
          >
            Return to Upload
          </button>
        </div>
      </div>
    );
  }
}
