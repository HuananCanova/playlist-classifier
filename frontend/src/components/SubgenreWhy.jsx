import React from "react";
import { Link } from "react-router-dom";
import { SERIES, NEUTRAL, pct } from "../charts/chartKit.js";

const FONTES = {
  track_tags: "Tags da faixa (Last.fm)",
  artist_tags: "Tags do artista (Last.fm)",
  tempo: "Andamento (Deezer)",
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
export function motivosIncerteza(evidence) {
  const fontes = new Set(evidence.map((e) => e.source));
  const itens = [];
  if (!fontes.has("tempo")) itens.push("sem BPM conhecido");
  else if (evidence.some((e) => e.source === "tempo" && !e.says)) itens.push("o BPM cabe em mais de um subgênero");
  if (!fontes.has("track_tags")) itens.push("o Last.fm só marca o artista, não a faixa");
  const porFonte = new Map();
  for (const e of evidence) {
    if (!e.says) continue;
    if (!porFonte.has(e.source)) porFonte.set(e.source, new Set());
    porFonte.get(e.source).add(e.says);
  }
  const conjuntos = [...porFonte.values()];
  const discordam = conjuntos.some((a, i) =>
    conjuntos.slice(i + 1).some((b) => ![...a].some((x) => b.has(x)))
  );
  if (discordam) itens.push("as fontes discordam");
  return itens;
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
  const falta = track.subgenre_unsure ? motivosIncerteza(evidence) : [];

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

      {track.subgenre_reference && <Referencia ref_={track.subgenre_reference} />}
    </section>
  );
}
