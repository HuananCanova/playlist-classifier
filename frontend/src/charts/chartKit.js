import { useEffect, useState } from "react";

/*
 * Peças comuns aos gráficos desenhados à mão em SVG.
 *
 * A paleta categórica foi validada contra a superfície dos painéis (#181818)
 * com o validador de paleta: nesta ordem, pares vizinhos passam no teste de
 * daltonismo (ΔE >= 9,4) e todas as seis cores têm contraste >= 3:1. A ordem é
 * o mecanismo de segurança — não reordene nem gere uma sétima cor; o que
 * passar de seis vira "outros".
 */
export const SERIES = ["#199e70", "#9085e9", "#d95926", "#3987e5", "#c98500", "#d55181"];

// "Outros" e "sem tag" não são entidades: ficam num cinza violáceo neutro.
export const NEUTRAL = "#535353";

export const SURFACE = "#181818";
export const GRID = "rgba(255, 255, 255, 0.07)";
export const INK = "#f2f2f2";
export const INK_MUTED = "#a7a7a7";

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

// Onde tentar pôr um rótulo em relação ao ponto da linha, na ordem de preferência.
const CALLOUT_OFFSETS = [
  [0, -30],
  [0, 30],
  [-54, -26],
  [54, -26],
  [-54, 26],
  [54, 26],
  [0, -50],
  [0, 50],
];
const CALLOUT_H = 18;

/**
 * Rótulos com fio para gráficos de linhas. Para cada série, procura o ponto em
 * que a linha dela está mais longe das outras e tenta encaixar o nome em volta
 * dele sem encostar em outro rótulo, numa área reservada (`reserved`, caixas
 * {x0, x1, y0, y1}) nem cruzar uma linha. Se nada couber, a série fica só na
 * legenda — um rótulo em cima de uma linha atrapalha mais do que ajuda.
 *
 * `series[k].label` dá o texto; `lines[k].pts` são os pontos [x, y] em pixels,
 * igualmente espaçados em x. Devolve, por rótulo posto: o ponto (x, y), o
 * centro do texto (lx, ly) e as pontas do fio (sx, sy → ex, ey).
 */
export function placeCallouts(series, lines, { left, right, top, bottom, reserved = [] }) {
  const boxes = [...reserved];
  const out = [];
  const n = lines[0]?.pts.length ?? 0;
  if (!n) return out;

  const hits = (b) =>
    boxes.some((o) => b.x0 < o.x1 + 6 && b.x1 > o.x0 - 6 && b.y0 < o.y1 + 4 && b.y1 > o.y0 - 4);

  // A altura de uma linha num x qualquer, entre os dois pontos vizinhos.
  const yAtX = (pts, x) => {
    if (n === 1) return pts[0][1];
    const step = (pts[n - 1][0] - pts[0][0]) / (n - 1) || 1;
    const f = Math.max(0, Math.min(n - 1, (x - pts[0][0]) / step));
    const i = Math.min(n - 2, Math.floor(f));
    return pts[i][1] + (pts[i + 1][1] - pts[i][1]) * (f - i);
  };
  const crossesLine = (b) =>
    lines.some(({ pts }) =>
      [0, 0.25, 0.5, 0.75, 1].some((t) => {
        const y = yAtX(pts, b.x0 + (b.x1 - b.x0) * t);
        return y > b.y0 - 3 && y < b.y1 + 3;
      }),
    );

  const lo = Math.ceil(n * 0.08);
  const hi = Math.floor(n * 0.92);
  const step = Math.max(1, Math.floor(n / 30));

  series.forEach((s, k) => {
    const own = lines[k].pts;
    const candidates = [];
    for (let i = lo; i <= hi && i < n; i += step) {
      const y = own[i][1];
      if (bottom - y < 6) continue; // colada no chão: ali o gênero quase não existe
      const sep = Math.min(80, ...lines.map((l, j) => (j === k ? 80 : Math.abs(l.pts[i][1] - y))));
      candidates.push({ i, sep, y });
    }
    candidates.sort((a, b) => b.sep - a.sep || a.y - b.y);

    const w = s.label.length * 7 + 8;
    for (const c of candidates.slice(0, 14)) {
      const [x, y] = own[c.i];
      const dot = { x0: x - 5, x1: x + 5, y0: y - 5, y1: y + 5 };
      if (hits(dot)) continue;
      const spot = CALLOUT_OFFSETS.map(([dx, dy]) => {
        const lx = x + dx;
        const ly = y + dy;
        return { lx, ly, box: { x0: lx - w / 2, x1: lx + w / 2, y0: ly - CALLOUT_H / 2, y1: ly + CALLOUT_H / 2 } };
      }).find(
        ({ box }) =>
          box.x0 >= left && box.x1 <= right && box.y0 >= top && box.y1 <= bottom && !hits(box) && !crossesLine(box),
      );
      if (!spot) continue;

      boxes.push(spot.box, dot);
      // O fio sai da borda do ponto e termina na borda do rótulo.
      const ex = spot.lx;
      const ey = spot.ly < y ? spot.box.y1 + 2 : spot.box.y0 - 2;
      const len = Math.hypot(ex - x, ey - y) || 1;
      out.push({
        k,
        x,
        y,
        lx: spot.lx,
        ly: spot.ly,
        sx: x + ((ex - x) / len) * 6,
        sy: y + ((ey - y) / len) * 6,
        ex,
        ey,
      });
      break;
    }
  });
  return out;
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

/*
 * Teto "redondo" para um eixo de valores. Sem isso o topo do eixo seria o
 * próprio valor máximo, e as marcas de grade cairiam em números sem leitura
 * (137, 68,5).
 *
 * Os passos são mais finos que o 1-2-5 de manual porque as marcas ficam em
 * 50% e 100% do teto: a metade de cada um destes ainda é um número limpo
 * (60 de 120, 120 de 240). Com só 1-2-5, um pico de 113 subia o eixo para 200
 * e a coluna mais alta do gráfico mal passava da metade da altura — todo o
 * desenho parecia pequeno por um arredondamento.
 */
const NICE_STEPS = [1, 1.2, 1.6, 2, 2.4, 3, 4, 5, 6, 8, 10];

export function niceMax(v) {
  if (v <= 4) return 4;
  const pow = 10 ** Math.floor(Math.log10(v));
  const n = v / pow;
  return (NICE_STEPS.find((s) => n <= s) ?? 10) * pow;
}

export function pct(part, whole) {
  if (!whole) return "0%";
  const v = (part / whole) * 100;
  return `${v < 10 && v > 0 ? v.toFixed(1).replace(".", ",") : Math.round(v)}%`;
}

export function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}
