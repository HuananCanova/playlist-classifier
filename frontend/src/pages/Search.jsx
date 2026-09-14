import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatWait } from "../api.js";

const EXEMPLOS = [
  "melancholic guitar",
  "energetic dance floor",
  "ambient and dreamy",
  "aggressive and heavy",
];

// Enquanto a varredura roda, o progresso é buscado nesse intervalo. Curto o
// bastante para a barra parecer viva, longo o bastante para não virar ruído.
const INTERVALO_PROGRESSO = 1500;

export default function Search() {
  const [consulta, setConsulta] = useState("");
  const [resultados, setResultados] = useState(null);
  const [buscando, setBuscando] = useState(false);
  const [erro, setErro] = useState(null);
  const [cobertura, setCobertura] = useState(null);
  const [indexacao, setIndexacao] = useState(null);
  const timer = useRef(null);

  const lerCobertura = useCallback(async () => {
    try {
      setCobertura(await api.searchStatus());
    } catch {
      setCobertura(null);
    }
  }, []);

  useEffect(() => {
    lerCobertura();
  }, [lerCobertura]);

  // Enquanto houver varredura, pergunta o progresso; quando ela termina,
  // relê a cobertura uma última vez para os números baterem.
  useEffect(() => {
    let vivo = true;

    async function tick() {
      try {
        const status = await api.indexStatus();
        if (!vivo) return;
        setIndexacao(status);
        if (!status.running) {
          clearInterval(timer.current);
          timer.current = null;
          lerCobertura();
        }
      } catch {
        clearInterval(timer.current);
        timer.current = null;
      }
    }

    tick();
    timer.current = setInterval(tick, INTERVALO_PROGRESSO);
    return () => {
      vivo = false;
      clearInterval(timer.current);
    };
  }, [lerCobertura]);

  async function indexar() {
    try {
      setIndexacao(await api.startIndex());
      if (!timer.current) {
        timer.current = setInterval(async () => {
          const status = await api.indexStatus();
          setIndexacao(status);
          if (!status.running) {
            clearInterval(timer.current);
            timer.current = null;
            lerCobertura();
          }
        }, INTERVALO_PROGRESSO);
      }
    } catch {
      setErro("Não consegui iniciar a varredura. Veja o log do backend.");
    }
  }

  async function pararIndexacao() {
    try {
      setIndexacao(await api.stopIndex());
    } catch {
      /* parar é best-effort; o próximo tick corrige o estado */
    }
    lerCobertura();
  }

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
  const rodando = indexacao?.running;

  return (
    <div className="container">
      <header className="search-head">
        <h1>Busca por descrição</h1>
        <p className="panel-sub">
          Descreva um clima, uma textura ou uma energia. A busca compara o sentido da frase com as tags das faixas que você já analisou, não as palavras exatas.
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

      <Cobertura
        cobertura={cobertura}
        indexacao={indexacao}
        rodando={rodando}
        onIndexar={indexar}
        onParar={pararIndexacao}
      />

      {erro && <div className="error-banner">{erro}</div>}

      {vazio && !erro && (
        <p className="spinner-text" style={{ marginTop: 32 }}>
          {cobertura?.pending_playlists > 0
            ? "Nada encontrado no que já foi indexado — e ainda faltam playlists."
            : "Nada parecido no seu acervo."}
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

/**
 * O que a busca já enxerga. Existe porque "não encontrei" e "ainda não olhei"
 * são respostas diferentes, e sem esse número elas ficam indistinguíveis.
 */
function Cobertura({ cobertura, indexacao, rodando, onIndexar, onParar }) {
  if (!cobertura) return null;

  const { indexed_tracks: faixas, indexed_playlists: feitas, total_playlists: total } = cobertura;
  const pendentes = cobertura.pending_playlists;
  const bloqueio = !rodando && (indexacao?.blocked_seconds || cobertura.blocked_seconds);
  const semDadosDoSpotify = total === null;
  const pct = total ? Math.round((feitas / total) * 100) : 0;

  return (
    <div className="coverage">
      <div className="coverage-top">
        <span className="coverage-label">
          {semDadosDoSpotify ? (
            <>
              <b>{faixas}</b> faixas no índice. Não consegui falar com o Spotify para
              saber quantas playlists faltam.
            </>
          ) : (
            <>
              <b>{feitas}</b> de <b>{total}</b> playlists indexadas, com <b>{faixas}</b> faixas.
              {pendentes > 0 && !rodando && (
                <> Faltam <b>{pendentes}</b>.</>
              )}
            </>
          )}
        </span>

        {rodando ? (
          <button className="btn btn-ghost btn-sm" onClick={onParar}>
            Parar
          </button>
        ) : (
          pendentes > 0 && (
            <button className="btn btn-sm" onClick={onIndexar} disabled={Boolean(bloqueio)}>
              Indexar {pendentes === 1 ? "a que falta" : `as ${pendentes} restantes`}
            </button>
          )
        )}
      </div>

      {bloqueio ? (
        <p className="coverage-errors">
          O Spotify suspendeu o acesso deste app por {formatWait(bloqueio)}. Nenhuma chamada sai até lá.
        </p>
      ) : (
        pendentes > 0 &&
        !rodando &&
        cobertura.estimated_calls != null && (
          <p className="coverage-note">
            Indexar o que falta custa ~{cobertura.estimated_calls} chamadas ao Spotify, uma playlist por vez com
            pausas. A mesma análise completa o seu perfil.
          </p>
        )
      )}

      {!semDadosDoSpotify && (
        <span className="coverage-bar">
          <span className="coverage-bar-fill" style={{ width: `${pct}%` }} />
        </span>
      )}

      {rodando && (
        <div className="coverage-running">
          <span className="typing-dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          {indexacao.waiting_seconds ? (
            <span>
              Pausa de {formatWait(indexacao.waiting_seconds)} para respeitar o limite do Spotify —
              a varredura continua sozinha.
            </span>
          ) : (
            <>
              <span>
                {indexacao.done}/{indexacao.total}
              </span>
              {indexacao.current && (
                <span className="coverage-current">{indexacao.current}</span>
              )}
            </>
          )}
        </div>
      )}

      {indexacao?.errors?.length > 0 && (
        <p className="coverage-errors">
          {indexacao.errors.length} playlist
          {indexacao.errors.length === 1 ? "" : "s"} falhou: {indexacao.errors.slice(0, 2).join("; ")}
        </p>
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
          <span className="hit-tags">{hit.tags.slice(0, 4).join(", ")}</span>
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
