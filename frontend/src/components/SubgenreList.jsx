import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import EnrichPanel from "./EnrichPanel.jsx";

const nf = new Intl.NumberFormat("pt-BR");

/** A seção "Subgêneros" do perfil: cada gênero com seus subgêneros e contagens. */
export default function SubgenreList() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const next = await api.getSubgenres();
      if (!alive.current) return;
      setRows(Array.isArray(next) ? next : []);
      setError(null);
    } catch (e) {
      if (alive.current) setError(e.message || "Não foi possível carregar os subgêneros.");
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    load();
    return () => {
      alive.current = false;
    };
  }, [load]);

  const groups = [];
  for (const r of rows ?? []) {
    let g = groups.find((x) => x.genre === r.genre);
    if (!g) groups.push((g = { genre: r.genre, items: [] }));
    g.items.push(r);
  }

  return (
    <section className="panel">
      <header className="panel-head">
        <h3>Subgêneros</h3>
        <p className="panel-sub">Como o acervo se divide dentro de cada gênero.</p>
      </header>

      <EnrichPanel onDone={load} />

      {error && (
        <div className="error-banner" role="alert">
          <span>{error}</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={load}>
            Tentar de novo
          </button>
        </div>
      )}

      {rows && rows.length === 0 && !error && (
        <p className="muted">
          Ainda não há subgêneros no acervo. Use “Buscar evidência” acima para reunir as tags e o BPM das faixas.
        </p>
      )}

      {groups.map((g) => (
        <div key={g.genre}>
          <h4>{g.genre}</h4>
          <ul className="cut-list">
            {g.items.map((s) => {
              const confident = s.confident ?? 0;
              const unsure = s.unsure ?? 0;
              const empty = confident + unsure === 0;
              return (
                <li key={s.name}>
                  <Link
                    to={`/subgenero/${encodeURIComponent(s.name)}`}
                    className="cut-row"
                    style={empty ? { opacity: 0.55 } : undefined}
                  >
                    <span className="cut-text">
                      <span className="cut-name">{s.name}</span>
                      <span className="cut-sub">
                        {Array.isArray(s.bpm) ? `${s.bpm[0]}–${s.bpm[1]} BPM` : "BPM desconhecido"}
                      </span>
                    </span>
                    <span className="cut-score">
                      {nf.format(confident)} classificadas · {nf.format(unsure)} incertas
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </section>
  );
}
