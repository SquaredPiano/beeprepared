"use client";

import { useEffect, useRef, useState } from "react";

import { getAccessToken } from "@/lib/auth";
import {
  ConnectionState,
  ProjectEvent,
  ProjectSocket,
} from "@/lib/realtime";

/**
 * Subscribe to a project's live event stream.
 *
 * The handler is kept in a ref rather than in the effect dependencies on
 * purpose: callers almost always pass an inline arrow function, and putting it
 * in the deps would tear down and re-open the WebSocket on every render.
 */
export function useProjectSocket(
  projectId: string | null,
  onEvent: (event: ProjectEvent) => void,
): { connection: ConnectionState; resync: () => void } {
  const [connection, setConnection] = useState<ConnectionState>("closed");
  const socketRef = useRef<ProjectSocket | null>(null);
  const handlerRef = useRef(onEvent);

  handlerRef.current = onEvent;

  useEffect(() => {
    if (!projectId) {
      setConnection("closed");
      return;
    }

    const socket = new ProjectSocket(projectId, getAccessToken);
    socketRef.current = socket;

    const unsubscribeEvents = socket.onEvent((event) => handlerRef.current(event));
    const unsubscribeState = socket.onStateChange(setConnection);
    void socket.connect();

    // A backgrounded tab can keep a socket that looks open but delivers
    // nothing. Ask for a fresh snapshot whenever the tab becomes visible.
    const onVisible = () => {
      if (document.visibilityState === "visible") socket.resync();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      unsubscribeEvents();
      unsubscribeState();
      socket.close();
      socketRef.current = null;
    };
  }, [projectId]);

  return {
    connection,
    resync: () => socketRef.current?.resync(),
  };
}
