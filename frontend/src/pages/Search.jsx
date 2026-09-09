import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";

const EXEMPLOS = [
  "melancholic guitar",
  "energetic dance floor",
  "ambient and dreamy",
  "aggressive and heavy",
];

export default function Search() {
  const [consulta, setConsulta] = useState("");
  const [resultados, setResultados] = useState(null);
  const [buscando, setBuscando] = useState(false);
  const [erro, setErro] = useState(null);
  const [indexadas, setIndexadas] = useState(null);

  useEffect(() => {
    api
      .searchStatus()
      .then((s) => setIndexadas(s.indexed_tracks))
      .catch(() => setIndexadas(0));
  }, []);

  async function buscar(texto) {
    const q = texto.trim();
    if (!q || buscando) return;

    setConsulta(q);
    setBuscando(true);
    setErro(null);
    try {
      setResultados(await api.search(q));
    } catch {
      setErro("A busca falhou. Veja o log do backend.");
      setResultados(null);
    } finally {
      setBuscando(false);
    }
  }

  const vazio = resultados !== null && resultados.length === 0;

  return (
    <div className="container">
      <header className="search-head">
        <h1>Busca por descrição</h1>
        <p className="panel-sub">
          Procure por clima, textura ou energia em vez de nome — a busca compara
          o sentido da frase com as tags das faixas, não as palavras.
        </p>
      </header>

      <form
        className="search-form"
        onSubmit={(e) => {
          e.preventDefault();
          buscar(consulta);
        }}
      >
        <input
          className="chat-input"
          value={consulta}
          onChange={(e) => setConsulta(e.target.value)}
          placeholder="melancholic guitar, upbeat electronic…"
          aria-label="Descrição a buscar"
          autoFocus
        />
        <button className="btn" type="submit" disabled={buscando || !consulta.trim()}>
          {buscando ? "Buscando…" : "Buscar"}
        </button>
      </form>

      <div className="search-examples">
        {EXEMPLOS.map((e) => (
          <button key={e} className="suggestion" onClick={() => buscar(e)}>
            {e}
          </button>
        ))}
      </div>

      {indexadas !== null && (
        <p className="search-index-note">
          {indexadas === 0
            ? "Nenhuma faixa indexada ainda — abra uma playlist para analisá-la e ela entra no índice."
            : `${indexadas} faixa${indexadas === 1 ? "" : "s"} no índice, de tudo que você já analisou.`}
        </p>
      )}

      {erro && <div className="error-banner">{erro}</div>}

      {vazio && !erro && (
        <p className="spinner-text" style={{ marginTop: 32 }}>
          Nada parecido no que já foi analisado.
        </p>
      )}

      {resultados && resultados.length > 0 && (
        <ul className="hit-list">
          {resultados.map((r) => (
            <li key={r.track_id}>
              <SearchHit hit={r} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Uma faixa devolvida pela busca. Também usada na página da faixa. */
export function SearchHit({ hit }) {
  return (
    <Link to={`/faixa/${hit.track_id}`} className="hit">
      <div className="hit-main">
        <span className="hit-name">{hit.nome}</span>
        <span className="hit-artists">{hit.artistas.join(", ")}</span>
        {hit.tags.length > 0 && (
          <span className="hit-tags">{hit.tags.slice(0, 4).join(" · ")}</span>
        )}
      </div>
      <SimilarityMeter valor={hit.similaridade} />
    </Link>
  );
}

/** Barra de proximidade. A similaridade cosseno aqui fica quase toda entre 0 e
 *  0,7, então a barra usa essa faixa — mapear 0–1 deixaria tudo parecendo fraco. */
function SimilarityMeter({ valor }) {
  const pct = Math.max(0, Math.min(100, (valor / 0.7) * 100));
  return (
    <span className="hit-meter" title={`Similaridade ${valor.toFixed(3)}`}>
      <span className="hit-meter-fill" style={{ width: `${pct}%` }} />
    </span>
  );
}
