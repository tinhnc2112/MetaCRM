export type ConnectionSnapshot = {
  /** Public HTTP liveness only; does not imply authentication or Messenger delivery. */
  backend: "REACHABLE" | "UNAVAILABLE";
};
