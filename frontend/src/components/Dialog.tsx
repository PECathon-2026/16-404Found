import { useEffect, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { motion } from 'motion/react'

export function Dialog({ title, onClose, children }: { title:string; onClose:()=>void; children:ReactNode }) {
  const ref=useRef<HTMLDialogElement>(null)
  useEffect(()=>{const el=ref.current!; el.showModal(); return()=>{el.close()}},[])
  return <dialog ref={ref} className="dialog" onCancel={onClose} onClick={e=>{if(e.target===ref.current)onClose()}} aria-labelledby="dialog-title">
    <motion.div initial={{opacity:0,y:16}} animate={{opacity:1,y:0}} transition={{duration:.3}} className="dialog-inner"><div className="dialog-header"><span className="eyebrow">DEV / MISSION CONTROL</span><button className="icon-button" onClick={onClose} aria-label="Close dialog"><X size={18}/></button></div><h2 id="dialog-title">{title}</h2>{children}</motion.div>
  </dialog>
}
