import { reportError } from "./api";

export function initErrorCapture(sampleId: string | null): () => void {
  const onError = (event: ErrorEvent) => {
    reportError({
      timestamp: new Date().toISOString(),
      page: window.location.pathname,
      error_type: "unhandled_exception",
      message: event.message,
      stack: event.error?.stack ?? null,
      user_agent: navigator.userAgent,
      sample_id: sampleId,
    });
  };

  const onRejection = (event: PromiseRejectionEvent) => {
    reportError({
      timestamp: new Date().toISOString(),
      page: window.location.pathname,
      error_type: "unhandled_rejection",
      message: String(event.reason),
      stack: event.reason?.stack ?? null,
      user_agent: navigator.userAgent,
      sample_id: sampleId,
    });
  };

  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onRejection);

  return () => {
    window.removeEventListener("error", onError);
    window.removeEventListener("unhandledrejection", onRejection);
  };
}
