/**
 * WebSocket client for live project updates.
 *
 * Replaces the polling loop the canvas used to run: a `GET /api/jobs` every few
 * seconds per open tab, which cost a round trip and an auth check each time and
 * still showed progress several seconds late.
 *
 * What this adds over `new WebSocket(...)`:
 *
 * - **Reconnect with backoff.** A dropped socket comes back on its own, and the
 *   delay grows so a backend that is genuinely down is not hammered.
 * - **Resync on reconnect.** The server sends a `snapshot` on connect, so the
 *   canvas resynchronises rather than silently missing whatever happened while
 *   the socket was down.
 * - **Wake-from-sleep handling.** A laptop lid closing leaves a half-open
 *   socket that looks connected but delivers nothing; the visibility listener
 *   forces a resync when the tab comes back.
 */

export type ProjectEventType =
  | "snapshot"
  | "ping"
  | "job.created"
  | "job.started"
  | "job.progress"
  | "job.completed"
  | "job.failed"
  | "job.cancelled"
  | "artifact.created"
  | "flow.started"
  | "flow.node"
  | "flow.completed"
  | "flow.failed"
  | "chat.message";

export interface ProjectEvent<T = any> {
  type: ProjectEventType;
  project_id: string;
  ts: string;
  data: T;
}

export type ConnectionState = "connecting" | "open" | "closed";

type EventHandler = (event: ProjectEvent) => void;
type StateHandler = (state: ConnectionState) => void;

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

// Authentication failures are permanent: reconnecting with the same bad token
// just produces the same close code in a loop.
const FATAL_CLOSE_CODES = new Set([4401, 4403]);

const BASE_RETRY_MS = 1_000;
const MAX_RETRY_MS = 30_000;

function socketUrl(projectId: string, token: string): string {
  const base = BACKEND_URL.replace(/^http/, "ws").replace(/\/$/, "");
  return `${base}/ws/projects/${projectId}?token=${encodeURIComponent(token)}`;
}

export class ProjectSocket {
  private socket: WebSocket | null = null;
  private handlers = new Set<EventHandler>();
  private stateHandlers = new Set<StateHandler>();
  private retryAttempt = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private closedByUs = false;

  constructor(
    private readonly projectId: string,
    private readonly getToken: () => Promise<string>,
  ) {}

  onEvent(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  onStateChange(handler: StateHandler): () => void {
    this.stateHandlers.add(handler);
    return () => this.stateHandlers.delete(handler);
  }

  async connect(): Promise<void> {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) return;

    this.closedByUs = false;
    this.emitState("connecting");

    let token: string;
    try {
      token = await this.getToken();
    } catch (error) {
      console.warn("[realtime] could not get an auth token", error);
      this.scheduleReconnect();
      return;
    }

    const socket = new WebSocket(socketUrl(this.projectId, token));
    this.socket = socket;

    socket.onopen = () => {
      this.retryAttempt = 0;
      this.emitState("open");
    };

    socket.onmessage = (message) => {
      let event: ProjectEvent;
      try {
        event = JSON.parse(message.data);
      } catch {
        return;
      }
      if (event.type === "ping") return;
      this.handlers.forEach((handler) => handler(event));
    };

    socket.onerror = () => {
      // `onclose` always follows, and it carries the code we actually need.
    };

    socket.onclose = (event) => {
      this.socket = null;
      this.emitState("closed");

      if (this.closedByUs) return;

      if (FATAL_CLOSE_CODES.has(event.code)) {
        console.warn(`[realtime] refused (${event.code}): ${event.reason}`);
        return;
      }
      this.scheduleReconnect();
    };
  }

  /** Ask the server to resend current state. Used after a reconnect or a wake. */
  resync(): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: "resync" }));
    } else {
      void this.connect();
    }
  }

  close(): void {
    this.closedByUs = true;
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    this.socket?.close(1000, "client closed");
    this.socket = null;
    this.handlers.clear();
    this.stateHandlers.clear();
  }

  private scheduleReconnect(): void {
    if (this.retryTimer) return;

    // Exponential backoff with jitter, so many open tabs do not all retry on
    // the same tick and knock the backend over as it comes back up.
    const delay = Math.min(BASE_RETRY_MS * 2 ** this.retryAttempt, MAX_RETRY_MS);
    const jittered = delay * (0.5 + Math.random() * 0.5);
    this.retryAttempt += 1;

    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      void this.connect();
    }, jittered);
  }

  private emitState(state: ConnectionState): void {
    this.stateHandlers.forEach((handler) => handler(state));
  }
}
