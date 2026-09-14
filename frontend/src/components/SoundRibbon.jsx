import React, { useEffect, useId, useRef } from "react";
import { prefersReducedMotion } from "../charts/chartKit.js";

const SAMPLES = 72;

/**
 * Relevo de linhas de onda — várias formas de onda empilhadas em perspectiva,
 * cada uma encobrindo a de trás, formando uma superfície que respira devagar.
 *
 * É decorativo (aria-hidden). Anima escrevendo o atributo `d` direto no DOM,
 * sem re-render do React; para quando a aba some ou quando o sistema pede
 * menos movimento, e aí desenha um único quadro parado.
 */
export default function SoundRibbon({ lines = 30, width = 1000, height = 420, className = "", speed = 1 }) {
  const pathsRef = useRef([]);
  const svgRef = useRef(null);
  const uid = useId().replace(/:/g, "");

  useEffect(() => {
    const paths = pathsRef.current;
    const gap = (height * 0.62) / lines;
    const top = height * 0.3;

    function frame(t) {
      for (let j = 0; j < lines; j++) {
        const depth = j / (lines - 1); // 0 = fundo, 1 = frente
        const base = top + j * gap;
        // O relevo é mais alto no meio das camadas, como um monte visto de lado.
        const envelope = Math.sin(Math.PI * (0.15 + depth * 0.8));
        const center = 0.5 + 0.16 * Math.sin(t * 0.00011 * speed + depth * 2.2);
        let d = "";
        for (let s = 0; s <= SAMPLES; s++) {
          const u = s / SAMPLES;
          const bump = Math.exp(-(((u - center) / 0.2) ** 2));
          const ripple =
            0.55 +
            0.3 * Math.sin(u * 17 + t * 0.0009 * speed + j * 0.45) +
            0.15 * Math.sin(u * 41 - t * 0.0014 * speed + j * 0.8);
          const y = base - bump * envelope * height * 0.36 * ripple;
          d += `${s === 0 ? "M" : "L"}${(u * width).toFixed(1)},${y.toFixed(1)}`;
        }
        const el = paths[j];
        if (!el?.fill || !el?.line) continue;
        el.fill.setAttribute("d", `${d}L${width},${height}L0,${height}Z`);
        el.line.setAttribute("d", d);
      }
    }

    if (prefersReducedMotion()) {
      frame(4000);
      return;
    }

    let raf = 0;
    let last = 0;
    let visible = true;
    const obs = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting;
    });
    if (svgRef.current) obs.observe(svgRef.current);

    const loop = (t) => {
      // ~30 quadros por segundo bastam para um movimento tão lento.
      if (visible && !document.hidden && t - last > 33) {
        frame(t);
        last = t;
      }
      raf = requestAnimationFrame(loop);
    };
    frame(0);
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      obs.disconnect();
    };
  }, [lines, width, height, speed]);

  return (
    <svg
      ref={svgRef}
      className={`ribbon ${className}`}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="xMidYMax slice"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id={`stroke-${uid}`} x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="#169c46" stopOpacity="0" />
          <stop offset="0.3" stopColor="#1ed760" />
          <stop offset="0.55" stopColor="#b8f5cd" />
          <stop offset="0.8" stopColor="#1ed760" />
          <stop offset="1" stopColor="#169c46" stopOpacity="0" />
        </linearGradient>
        <radialGradient id={`glow-${uid}`} cx="0.5" cy="0.62" r="0.5">
          <stop offset="0" stopColor="#1db954" stopOpacity="0.5" />
          <stop offset="1" stopColor="#1db954" stopOpacity="0" />
        </radialGradient>
      </defs>
      <ellipse cx={width / 2} cy={height * 0.62} rx={width * 0.42} ry={height * 0.4} fill={`url(#glow-${uid})`} />
      {Array.from({ length: lines }).map((_, j) => {
        const depth = j / (lines - 1);
        return (
          <g key={j}>
            <path
              ref={(el) => {
                pathsRef.current[j] = { ...(pathsRef.current[j] || {}), fill: el };
              }}
              className="ribbon-occlude"
            />
            <path
              ref={(el) => {
                pathsRef.current[j] = { ...(pathsRef.current[j] || {}), line: el };
              }}
              fill="none"
              stroke={`url(#stroke-${uid})`}
              strokeWidth={0.8 + depth * 1.1}
              strokeOpacity={0.25 + depth * 0.75}
              strokeLinejoin="round"
            />
          </g>
        );
      })}
    </svg>
  );
}
