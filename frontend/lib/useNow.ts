"use client";
import { useSyncExternalStore } from "react";

const subscribe = (cb: () => void) => { const t = setInterval(cb, 1000); return () => clearInterval(t); };
/** Current time in ms from an external 1s clock; 0 during server prerender (so render stays pure). */
export const useNow = () => useSyncExternalStore(subscribe, () => Math.floor(Date.now() / 1000) * 1000, () => 0);
