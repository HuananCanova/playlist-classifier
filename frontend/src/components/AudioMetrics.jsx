import React, { useEffect, useRef, useState } from "react";
import { analisarPrevia } from "../audioAnalysis.js";
import { usePlayer } from "../PlayerContext.jsx";

const ACCENT = "#19a44a";
const ACCENT_DIM = "rgba(25, 164, 74, 0.32)";
const GRID = "#2a2a35";

/**
 * Panorama da prévia: a onda inteira desenhada de uma vez, com a posição da
 * reprodução por cima, mais as métricas medidas do sinal.
 *
 * Complementa o osciloscópio ao vivo — este mostra a forma da faixa toda, aquele
 * mostra o instante. Clicar na onda navega para aquele ponto.
 */
export default function AudioMetrics({ track }) {
  const { track: atual, time, seek, playTrack } = usePlayer();
  const canvasRef = useRef(null);
  const [analise, setAnalise] = useState(null);
  const [erro, setErro] = useState(null);

  const estaAqui = atual?.track_id === track.track_id;

  useEffect(() => {
    let cancelado = false;
    setAnalise(null);
    setErro(null);

    analisarPrevia(track.preview_url)
      .then((r) => !cancelado && setAnalise(r))
      .catch(() => !cancelado && setErro("Não consegui analisar o áudio desta prévia."));

    return () => {
      cancelado = true;
    };
  }, [track.preview_url]);

  const [largura, setLargura] = useState(0);

  // O canvas pode ser medido antes de o layout lhe dar largura, e precisa ser
  // redesenhado quando a janela muda de tamanho — nos dois casos sem o
  // ResizeObserver a onda sai em branco ou esticada.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const obs = new ResizeObserver(([entrada]) => {
      setLargura(Math.round(entrada.contentRect.width));
    });
    obs.observe(canvas);
    return () => obs.disconnect();
  }, [analise]);

  // Redesenha quando a análise chega, a posição muda ou a largura muda.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !analise) return;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return; // ainda sem layout: o observer chama de novo
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);

    const g = canvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);

    const picos = analise.picos;
    const baldes = picos.length / 2;
    const larguraBalde = w / baldes;
    const meio = h / 2;
    const progresso = estaAqui && analise.duracao ? time / analise.duracao : 0;
    const xTocado = progresso * w;

    for (let b = 0; b < baldes; b++) {
      const min = picos[b * 2];
      const max = picos[b * 2 + 1];
      const x = b * larguraBalde;
      const y1 = meio - max * meio * 0.94;
      const y2 = meio - min * meio * 0.94;
      // A parte já tocada fica sólida; o resto, esmaecido.
      g.fillStyle = x < xTocado ? ACCENT : ACCENT_DIM;
      g.fillRect(x, y1, Math.max(larguraBalde - 0.5, 0.5), Math.max(y2 - y1, 1));
    }

    g.strokeStyle = GRID;
    g.lineWidth = 1;
    g.beginPath();
    g.moveTo(0, meio);
    g.lineTo(w, meio);
    g.stroke();

    if (estaAqui && progresso > 0) {
      g.strokeStyle = "#eafff2";
      g.lineWidth = 2;
      g.beginPath();
      g.moveTo(xTocado, 0);
      g.lineTo(xTocado, h);
      g.stroke();
    }
  }, [analise, time, estaAqui, largura]);

  if (erro) return <p className="muted panel-empty">{erro}</p>;

  if (!analise) {
    return (
      <div className="metrics-loading">
        <div className="skeleton" style={{ height: 96, borderRadius: 10 }} />
        <p className="muted" style={{ fontSize: 12.5, marginTop: 12 }}>
          Baixando e decodificando a prévia…
        </p>
      </div>
    );
  }

  const m = analise.metricas;

  return (
    <div className="metrics">
      <canvas
        ref={canvasRef}
        className="overview-canvas"
        role="img"
        aria-label={`Forma de onda completa de ${track.name}`}
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const alvo = ((e.clientX - r.left) / r.width) * analise.duracao;
          if (estaAqui) seek(alvo);
          else playTrack(track);
        }}
      />

      <div className="metric-grid">
        <Metric
          rotulo="Volume médio"
          valor={`${m.rmsDb.toFixed(1)} dB`}
          nota="RMS, em dBFS (0 é o teto digital)"
        />
        <Metric rotulo="Pico" valor={`${m.peakDb.toFixed(1)} dB`} nota="amostra mais alta" />
        <Metric
          rotulo="Dinâmica"
          valor={`${m.crest.toFixed(1)} dB`}
          nota={
            m.crest < 9
              ? "fator de crista baixo — masterização comprimida"
              : m.crest > 16
              ? "fator de crista alto — dinâmica preservada"
              : "fator de crista típico"
          }
        />
        <Metric
          rotulo="Brilho"
          valor={`${m.centroideHz} Hz`}
          nota="centroide espectral: onde está o centro de massa do som"
        />
      </div>

      <div className="bandas">
        <p className="bandas-titulo">Distribuição de energia</p>
        <div className="bandas-barra" role="img"
             aria-label={`Graves ${m.bandas.graves}%, médios ${m.bandas.medios}%, agudos ${m.bandas.agudos}%`}>
          <span className="banda banda-graves" style={{ width: `${m.bandas.graves}%` }} />
          <span className="banda banda-medios" style={{ width: `${m.bandas.medios}%` }} />
          <span className="banda banda-agudos" style={{ width: `${m.bandas.agudos}%` }} />
        </div>
        <div className="bandas-legenda">
          <span><i className="ponto ponto-graves" />Graves {m.bandas.graves}% <em>&lt;250 Hz</em></span>
          <span><i className="ponto ponto-medios" />Médios {m.bandas.medios}% <em>250 Hz–4 kHz</em></span>
          <span><i className="ponto ponto-agudos" />Agudos {m.bandas.agudos}% <em>&gt;4 kHz</em></span>
        </div>
      </div>

      <p className="metrics-fonte muted">
        Medido dos {analise.duracao.toFixed(0)}s da prévia · {analise.taxaAmostragem / 1000} kHz ·{" "}
        {analise.canais === 2 ? "estéreo" : "mono"}
      </p>
    </div>
  );
}

function Metric({ rotulo, valor, nota }) {
  return (
    <div className="metric">
      <span className="metric-rotulo">{rotulo}</span>
      <span className="metric-valor tabular">{valor}</span>
      <span className="metric-nota">{nota}</span>
    </div>
  );
}
