import React from "react";
import { Link } from "react-router-dom";
import { SERIES, NEUTRAL, pct } from "../charts/chartKit.js";

const FONTES = {
  track_tags: "Tags da faixa (Last.fm)",
  artist_tags: "Tags do artista (Last.fm)",
  tempo: "Andamento (Deezer)",
  label: "Selo (Deezer)",
};

// Os quatro maiores ganham cor; o resto vira "outros", em cinza.
function segmentos(blend) {
  const ordenado = [...blend].sort((a, b) => b.share - a.share);
  const topo = ordenado.slice(0, 4).map((b, i) => ({ label: b.label, share: b.share, cor: SERIES[i] }));
  const resto = ordenado.slice(4).reduce((soma, b) => soma + b.share, 0);
  if (resto > 0) topo.push({ label: "outros", share: resto, cor: NEUTRAL });
  return topo;
}

// O que faltou, deduzido de quais fontes aparecem na evidência.
// "As fontes discordam" só vale entre fontes distintas: cada fonte vira o
// conjunto do que ela diz (a fonte de tags emite uma linha por tag), e há
// discordância quando duas fontes têm conjuntos disjuntos. Sobreposição conta
// como acordo. Ex.: artist_tags {full-on, darkpsy} sozinha não discorda; com
// tempo {goa}, sim. O andamento empatado vem com `says` nulo (o backend não
// escolhe um dos empatados), então não entra na comparação.
// O selo entra como as outras fontes. Quando ele reparte entre subgêneros,
// também vem com `says` nulo — mas aí sabemos entre quais: as fatias do mapa
// (`label_info.shares`) que estão na mistura, isto é, as deste gênero. O
// conjunto do selo são essas fatias, e sobreposição com outra fonte é acordo.
export function motivosIncerteza(evidence, { label = null, label_info = null, subgenre_blend = [] } = {}) {
  const fontes = new Set(evidence.map((e) => e.source));
  const itens = [];
  if (!fontes.has("tempo")) itens.push("sem BPM conhecido");
  else if (evidence.some((e) => e.source === "tempo" && !e.says)) itens.push("o BPM cabe em mais de um subgênero");
  if (!fontes.has("track_tags")) itens.push("o Last.fm só marca o artista, não a faixa");
  if (!fontes.has("label")) {
    // Sem voto do selo: ou não há selo, ou ele não está no mapa, ou está no
    // mapa só com subgêneros de outro gênero (aí ele se abstém).
    if (!label) itens.push("sem selo conhecido");
    else if (!label_info) itens.push("selo fora do mapa");
    else itens.push("o selo lança outros estilos, não este gênero");
  }
  const naMistura = new Set(subgenre_blend.map((b) => b.label));
  const porFonte = new Map();
  const juntar = (fonte, says) => {
    if (!porFonte.has(fonte)) porFonte.set(fonte, new Set());
    porFonte.get(fonte).add(says);
  };
  for (const e of evidence) {
    if (e.says) juntar(e.source, e.says);
    else if (e.source === "label" && label_info) {
      for (const s of label_info.shares || []) if (naMistura.has(s.label)) juntar("label", s.label);
    }
  }
  const conjuntos = [...porFonte.values()];
  const discordam = conjuntos.some((a, i) =>
    conjuntos.slice(i + 1).some((b) => ![...a].some((x) => b.has(x)))
  );
  if (discordam) itens.push("as fontes discordam");
  return itens;
}

// O selo segundo o nosso mapa: nome, nota, fatias em palavras e a fonte.
// As fatias não são filtradas pelo gênero da faixa — é o catálogo do selo.
function Selo({ info, comoVeio }) {
  const fatias = (info.shares || []).map((s) => `${s.label} ${pct(s.share, 1)}`).join(", ");
  const fonte = info.fonte ? (
    <a href={info.fonte} target="_blank" rel="noopener noreferrer">
      {hostDe(info.fonte)}
    </a>
  ) : null;
  // O Deezer pode grafar o selo de outro jeito; mostramos a grafia dele também.
  const outraGrafia = comoVeio && comoVeio.toLowerCase() !== info.name.toLowerCase() ? comoVeio : null;
  return (
    <div className="subgenre-ref">
      <p>
        <span className="muted">Selo</span> <strong>{info.name}</strong>
        {outraGrafia && <span className="muted"> (no Deezer: {outraGrafia})</span>}
        {fatias ? `: ${fatias}` : ""}
        {fonte ? <>, segundo {fonte}</> : null}
      </p>
      {info.nota && <p className="muted">{info.nota}</p>}
    </div>
  );
}

function Referencia({ ref_ }) {
  const nome = ref_.name.charAt(0).toUpperCase() + ref_.name.slice(1);
  const link = <Link to={`/subgenero/${encodeURIComponent(ref_.name)}`}>{nome}</Link>;
  const fonte = ref_.source ? (
    <a href={ref_.source} target="_blank" rel="noopener noreferrer">
      {hostDe(ref_.source)}
    </a>
  ) : null;
  const faixa = ref_.bpm && ref_.bpm.length === 2 ? `${ref_.bpm[0]}–${ref_.bpm[1]} BPM` : null;
  return (
    <div className="subgenre-ref">
      <p>
        {link}
        {faixa ? `: ${faixa}` : ""}
        {fonte ? <>{faixa ? ", " : ", "}segundo {fonte}</> : null}
      </p>
      {ref_.about && <p className="muted">{ref_.about}</p>}
    </div>
  );
}

function hostDe(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export default function SubgenreWhy({ track }) {
  const blend = track.subgenre_blend || [];
  if (blend.length === 0) return null;
  const evidence = track.subgenre_evidence || [];
  const segs = segmentos(blend);
  const falta = track.subgenre_unsure ? motivosIncerteza(evidence, track) : [];

  return (
    <section className="panel">
      <header className="panel-head">
        <h3>Por que este subgênero</h3>
        <p className="panel-sub">A mistura que o classificador enxergou e as fontes que a formaram</p>
      </header>

      <div className="why-bar" role="img" aria-label={segs.map((s) => `${s.label} ${pct(s.share, 1)}`).join(", ")}>
        {segs.map((s) => (
          <span
            key={s.label}
            className="why-seg"
            style={{ width: `${s.share * 100}%`, background: s.cor }}
            title={`${s.label} — ${pct(s.share, 1)}`}
          />
        ))}
      </div>
      <ul className="why-legend">
        {segs.map((s) => (
          <li key={s.label}>
            <span className="why-dot" style={{ background: s.cor }} aria-hidden="true" />
            {s.label} <span className="muted tabular">{pct(s.share, 1)}</span>
          </li>
        ))}
      </ul>

      {track.subgenre_unsure && (
        <p className="why-unsure">
          Incerto{falta.length ? ` porque: ${falta.join("; ")}` : ""}.
        </p>
      )}

      {evidence.length > 0 && (
        <ul className="why-evidence">
          {evidence.map((e, i) => (
            <li key={`${e.source}-${i}`}>
              <strong>{FONTES[e.source] || e.source}:</strong> {e.detail}
            </li>
          ))}
        </ul>
      )}

      {track.label_info && <Selo info={track.label_info} comoVeio={track.label} />}

      {track.subgenre_reference && <Referencia ref_={track.subgenre_reference} />}
    </section>
  );
}
