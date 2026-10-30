"use client";
import { useSyncExternalStore } from "react";

const listeners = new Set<() => void>();
const subscribe = (cb: () => void) => { listeners.add(cb); window.addEventListener("storage", cb); return () => { listeners.delete(cb); window.removeEventListener("storage", cb); }; };
/** Display name from localStorage as an external store: SSR renders the default, the client swaps in the saved name without a hydration mismatch. */
export const useName = () => useSyncExternalStore(subscribe, () => localStorage.getItem("dp-name") || "Commander", () => "Commander");
export const saveName = (v: string) => { localStorage.setItem("dp-name", v.trim()); listeners.forEach((l) => l()); };
