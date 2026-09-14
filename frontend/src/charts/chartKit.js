import { useEffect, useState } from "react";

/*
 * Peças comuns aos gráficos desenhados à mão em SVG.
 *
 * A paleta categórica foi validada contra a superfície dos painéis (#17141f)
 * com o validador de paleta: nesta ordem, pares vizinhos passam no teste de
 * daltonismo (ΔE >= 9,4) e todas as seis cores têm contraste >= 3:1. A ordem é
 * o mecanismo de segurança — não reordene nem gere uma sétima cor; o que
 * passar de seis vira "outros".
 */
export const SERIES = ["#9085e9", "#199e70", "#d95926", "#3987e5", "#c98500", "#d55181"];

// "Outros" e "sem tag" não são entidades: ficam num cinza violáceo neutro.
export const NEUTRAL = "#4d4862";

export const SURFACE = "#17141f";
export const GRID = "rgba(255, 255, 255, 0.07)";
export const INK = "#eeebf7";
export const INK_MUTED = "#9d97b3";

/**
 * Largura real do elemento, atualizada em resize. SVG responsivo sem viewBox esticado.
 *
 * Devolve um ref de callback, não um useRef: o elemento medido costuma surgir
 * depois do primeiro render (quando o carregamento termina), e um efeito que
 * lê `ref.current` só na montagem nunca o veria.
 */
export function useWidth() {
  const [node, setNode] = useState(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    if (!node) return;
    const obs = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    obs.observe(node);
    return () => obs.disconnect();
  }, [node]);

  return [setNode, width];
}

/** true uma única vez, logo depois da primeira pintura — dispara as transições de entrada. */
export function useMounted() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => requestAnimationFrame(() => setMounted(true)));
    return () => cancelAnimationFrame(id);
  }, []);
  return mounted;
}

export function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Curva suave por pontos, monotônica em x (Fritsch–Carlson): passa por todos
 * os pontos sem "ultrapassar" — uma curva que inventa picos entre duas
 * amostras mentiria sobre os dados.
 */
export function smoothPath(points, { move = true } = {}) {
  const n = points.length;
  if (n === 0) return "";
  if (n === 1) return `${move ? "M" : "L"}${points[0][0]},${points[0][1]}`;

  const dx = [];
  const slope = [];
  for (let i = 0; i < n - 1; i++) {
    dx[i] = points[i + 1][0] - points[i][0];
    slope[i] = dx[i] === 0 ? 0 : (points[i + 1][1] - points[i][1]) / dx[i];
  }

  const t = new Array(n);
  t[0] = slope[0];
  t[n - 1] = slope[n - 2];
  for (let i = 1; i < n - 1; i++) {
    t[i] = slope[i - 1] * slope[i] <= 0 ? 0 : (slope[i - 1] + slope[i]) / 2;
  }
  for (let i = 0; i < n - 1; i++) {
    if (slope[i] === 0) {
      t[i] = 0;
      t[i + 1] = 0;
      continue;
    }
    const a = t[i] / slope[i];
    const b = t[i + 1] / slope[i];
    const h = a * a + b * b;
    if (h > 9) {
      const k = 3 / Math.sqrt(h);
      t[i] = k * a * slope[i];
      t[i + 1] = k * b * slope[i];
    }
  }

  let d = `${move ? "M" : "L"}${points[0][0]},${points[0][1]}`;
  for (let i = 0; i < n - 1; i++) {
    const [x0, y0] = points[i];
    const [x1, y1] = points[i + 1];
    const h = dx[i] / 3;
    d += `C${x0 + h},${y0 + t[i] * h} ${x1 - h},${y1 - t[i + 1] * h} ${x1},${y1}`;
  }
  return d;
}

/** Suavização gaussiana de uma série, com as bordas renormalizadas. */
export function gaussianSmooth(values, sigma) {
  const n = values.length;
  if (sigma <= 0 || n < 3) return values.slice();
  const radius = Math.ceil(sigma * 3);
  const kernel = [];
  for (let k = -radius; k <= radius; k++) kernel.push(Math.exp(-(k * k) / (2 * sigma * sigma)));

  return values.map((_, i) => {
    let sum = 0;
    let weight = 0;
    for (let k = -radius; k <= radius; k++) {
      const j = i + k;
      if (j < 0 || j >= n) continue;
      const w = kernel[k + radius];
      sum += values[j] * w;
      weight += w;
    }
    return weight ? sum / weight : 0;
  });
}

export function pct(part, whole) {
  if (!whole) return "0%";
  const v = (part / whole) * 100;
  return `${v < 10 && v > 0 ? v.toFixed(1).replace(".", ",") : Math.round(v)}%`;
}

export function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}
