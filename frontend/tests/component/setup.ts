import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  // A test file may run in the node environment, which has no window.
  if (typeof window === "undefined") return;
  window.localStorage.clear();
  window.sessionStorage.clear();
});
