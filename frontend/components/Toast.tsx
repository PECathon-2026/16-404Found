"use client";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Info, XCircle } from "lucide-react";
import React, { createContext, useCallback, useContext, useState } from "react";

type T = { id: number; tone: "success" | "error" | "info"; text: string };
const Ctx = createContext<(tone: T["tone"], text: string) => void>(() => {});
export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<T[]>([]);
  const push = useCallback((tone: T["tone"], text: string) => {
    const id = Date.now() + Math.random();
    setItems((s) => [...s.slice(-3), { id, tone, text }]);
    setTimeout(() => setItems((s) => s.filter((x) => x.id !== id)), 4500);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-20 right-4 z-[60] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2 md:bottom-4">
        <AnimatePresence>{items.map((t) => (
          <motion.div key={t.id} initial={{ opacity: 0, y: 12, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, x: 24 }} role="status"
            className="glass pointer-events-auto flex items-start gap-2 rounded-lg px-3 py-2 text-sm">
            {t.tone === "success" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" /> : t.tone === "error" ? <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" /> : <Info className="mt-0.5 h-4 w-4 shrink-0 text-cyan" />}
            <span className="text-fg">{t.text}</span></motion.div>))}</AnimatePresence>
      </div>
    </Ctx.Provider>
  );
}
