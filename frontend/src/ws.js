import { useEffect, useRef } from "react";

const listeners = new Set();
let socket = null;
let reconnectTimer = null;

function buildWsUrl() {
  const explicit = import.meta.env.VITE_WS_URL;
  const token = import.meta.env.VITE_APP_TOKEN;
  let url = explicit;
  if (!url) {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    url = `${proto}://${window.location.host}/ws`;
  }
  if (token) {
    const sep = url.includes("?") ? "&" : "?";
    url = `${url}${sep}token=${encodeURIComponent(token)}`;
  }
  return url;
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, 3000);
}

function connect() {
  socket = new WebSocket(buildWsUrl());
  socket.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      listeners.forEach((fn) => fn(data));
    } catch {}
  };
  socket.onclose = () => {
    socket = null;
    scheduleReconnect();
  };
  socket.onerror = () => {
    try {
      socket?.close();
    } catch {}
  };
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
