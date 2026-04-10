import { useEffect, useRef } from "react";

const listeners = new Set();
let socket = null;

function connect() {
  socket = new WebSocket("ws://localhost:8000/ws");
  socket.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      listeners.forEach((fn) => fn(data));
    } catch {}
  };
  socket.onclose = () => setTimeout(connect, 3000);
}

export function onWsMessage(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useWS() {
  useEffect(() => {
    if (!socket) connect();
  }, []);
}

export function useWsEvent(fn) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    const handler = (data) => ref.current(data);
    const off = onWsMessage(handler);
    return off;
  }, []);
}
