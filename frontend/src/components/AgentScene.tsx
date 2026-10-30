/** Procedural, animated agent identities. No video assets or fabricated runtime data. */
import { useEffect, useRef } from 'react'
import { AGENTS, type AgentId } from '../lib/types'

type Point = [number, number, number]
function rotate([x, y, z]: Point, angle: number, tilt: number): Point {
  const a = x * Math.cos(angle) - z * Math.sin(angle)
  const b = x * Math.sin(angle) + z * Math.cos(angle)
  return [a, y * Math.cos(tilt) - b * Math.sin(tilt), y * Math.sin(tilt) + b * Math.cos(tilt)]
}

export function AgentScene({ agent = 'master', className = '', paused = false }: { agent?: AgentId; className?: string; paused?: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const element = canvas.current!
    const ctx = element.getContext('2d')
    if (!ctx) return
    let frame = 0, width = 0, height = 0, start = performance.now()
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    let reduced = media.matches
    let redraw: (() => void) | undefined
    const resize = () => {
      const bounds = element.getBoundingClientRect()
      width = bounds.width; height = bounds.height
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      element.width = width * ratio; element.height = height * ratio
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
      redraw?.()
    }
    const observer = new ResizeObserver(resize)
    observer.observe(element); resize()
    const color = AGENTS[agent].color
    const draw = (now: number) => {
      const t = paused || reduced ? 0.6 : Math.max(0, (now - start) / 1000)
      ctx.clearRect(0, 0, width, height)
      const size = Math.min(width * .36, height * .37)
      const cx = width * .5, cy = height * .48
      const project = (point: Point): [number, number, number] => {
        const [x, y, z] = rotate(point, t * .13, .32 + Math.sin(t * .08) * .12)
        const depth = 3.2 / (3.2 + z)
        return [cx + x * size * depth, cy + y * size * depth, z]
      }
      const line = (points: Point[], alpha: number, lineWidth = .6) => {
        ctx.beginPath()
        points.forEach((p, index) => { const [x, y] = project(p); if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y) })
        ctx.strokeStyle = color; ctx.globalAlpha = alpha; ctx.lineWidth = lineWidth; ctx.stroke()
      }
      const dot = (point: Point, alpha = .7, radius = 1) => {
        const [x, y, z] = project(point)
        ctx.globalAlpha = alpha * Math.max(.15, (1.4 - z) / 2.4)
        ctx.fillStyle = color; ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fill()
      }
      if (agent === 'planner') {
        for (let n = 0; n < 5; n++) {
          const r = .72 + n * .09
          const corners: Point[] = [[-r,-r,-r],[r,-r,-r],[r,r,-r],[-r,r,-r],[-r,-r,r],[r,-r,r],[r,r,r],[-r,r,r]]
          const rotated = corners.map(p => rotate(p, n * .09, n * .05))
          for (const [a,b] of [[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]]) line([rotated[a],rotated[b]], .2 + n*.07, n===4?1:.5)
          rotated.forEach(p => dot(p, .9, 2))
        }
        for (let i = -4; i <= 4; i++) {
          line([[-1.12,i*.25,1.12],[1.12,i*.25,1.12]], .12)
          line([[i*.25,-1.12,1.12],[i*.25,1.12,1.12]], .12)
        }
      } else if (agent === 'developer') {
        for (let layer = 0; layer < 55; layer++) {
          const points: Point[] = []
          const offset = (layer-27)/24
          for (let i = 0; i <= 90; i++) {
            const x = (i/90 - .5)*2.65
            const twist = x * 1.5 + t*.4
            points.push([x, Math.sin(twist)*offset, Math.cos(twist)*offset])
          }
          line(points, .2 + Math.sin(layer*.17 + t)*.1, .8)
          dot(points[(Math.floor(t*6)+layer*3)%90], .9, 1.5)
        }
      } else if (agent === 'verifier') {
        for (let ring = 0; ring < 24; ring++) {
          const v = ring/24*Math.PI*2, points: Point[] = []
          for (let i = 0; i <= 100; i++) {
            const u = i/100*Math.PI*2
            const r = .92 + .34*Math.cos(v+t*.14)
            points.push([r*Math.cos(u), .34*Math.sin(v+t*.14), r*Math.sin(u)])
          }
          line(points, .19 + (ring%4===0?.15:0))
          dot(points[(Math.floor(t*10)+ring*7)%100], .9, 1.6)
        }
        for (let i=0;i<12;i++) {
          const angle = i/12*Math.PI*2
          const points: Point[] = []
          for(let n=0;n<=80;n++) { const v=n/80*Math.PI*2; const r=.92+.34*Math.cos(v); points.push([r*Math.cos(angle),.34*Math.sin(v),r*Math.sin(angle)]) }
          line(points,.25)
        }
      } else if (agent === 'reviewer') {
        for (let layer=0;layer<22;layer++) {
          const r=.18+layer*.044, z=(layer-11)*.055
          const points: Point[]=[]
          for(let n=0;n<=6;n++) { const a=n/6*Math.PI*2-Math.PI/2; points.push([Math.cos(a)*r,Math.sin(a)*r*1.17,z]) }
          line(points,.15+layer*.014,layer===21?1.3:.8)
          dot(points[layer%6],.7,1.5)
        }
        for(let n=0;n<6;n++) { const a=n/6*Math.PI*2-Math.PI/2; line([[Math.cos(a)*1.11,Math.sin(a)*1.30,.55],[0,0,-.85]],.2) }
      } else {
        for (let lat=1;lat<30;lat++) {
          const phi=lat/30*Math.PI, points: Point[]=[]
          for(let lon=0;lon<=90;lon++) { const theta=lon/90*Math.PI*2; points.push([Math.sin(phi)*Math.cos(theta),Math.cos(phi),Math.sin(phi)*Math.sin(theta)]) }
          line(points,.11)
          points.forEach((p,i)=>{ if(i%3===0) dot(p,.65,lat%5===0?1.1:.65) })
        }
        for (let ring=0;ring<3;ring++) {
          const points: Point[]=[]
          for(let i=0;i<=160;i++) { const a=i/160*Math.PI*2; points.push(rotate([Math.cos(a)*1.37,0,Math.sin(a)*1.37],ring*.55,ring*.61+.4)) }
          line(points,.15,.8)
          dot(points[Math.floor(t*11+ring*53)%160],1,3)
        }
      }
      ctx.globalAlpha = 1
      if (!document.hidden && !reduced && !paused) frame = requestAnimationFrame(draw)
    }
    const restart = () => { cancelAnimationFrame(frame); start=performance.now(); draw(start) }
    redraw = restart
    const visibility = () => { if (document.hidden) cancelAnimationFrame(frame); else restart() }
    const preference = () => { reduced=media.matches; restart() }
    document.addEventListener('visibilitychange',visibility)
    media.addEventListener('change',preference)
    restart()
    return () => { cancelAnimationFrame(frame); observer.disconnect(); document.removeEventListener('visibilitychange',visibility); media.removeEventListener('change',preference) }
  }, [agent, paused])
  return <canvas ref={canvas} className={`agent-scene ${className}`} aria-hidden="true" />
}
