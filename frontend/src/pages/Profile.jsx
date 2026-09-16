import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useAuth } from "../AuthContext.jsx";
import ColumnChart from "../components/ColumnChart.jsx";
import DistributionBarChart from "../components/DistributionBarChart.jsx";
import TasteTimeline from "../charts/TasteTimeline.jsx";
import { NEUTRAL, SERIES, pct } from "../charts/chartKit.js";

/*
 * O perfil é um retrato do gosto, não um relatório da biblioteca. Cada peça
 * desta página responde "o que essa pessoa ouve?" — gênero, época, artistas,
 * o quanto o gosto é concentrado, onde ele cai entre o hit e o garimpo, em que
 * andamento, e como tudo isso mudou. Número que não responde a isso (faixa
 * explícita, faixa repetida em duas playlists) não entra: é fato do acervo, e
 * ocupa o lugar de algo que diria alguma coisa sobre a pessoa.
 */

// Enquanto a varredura roda, o painel se atualiza neste ritmo. Cada consulta é
// barata no backend (lê resumos em disco), então dá para ser frequente.
const POLL_MS = 2500;

// A mesma ordem de séries do backend (TASTE_SERIES) e da linha do gosto: o
// gênero que é verde no gráfico continua verde na barra, na página inteira.
const TASTE_SERIES = 5;

const nf = new Intl.NumberFormat("pt-BR");
const dateFmt = new Intl.DateTimeFormat("pt-BR", { month: "long", year: "numeric", timeZone: "UTC" });

function hours(ms) {
  const h = ms / 3_600_000;
  return h >= 10 ? `${nf.format(Math.round(h))} h` : `${h.toFixed(1).replace(".", ",")} h`;
}

function decimal(v) {
  return v.toLocaleString("pt-BR", { maximumFractionDigits: 1 });
}

// Número efetivo (gêneros, artistas) dito como quantidade: "196,3 artistas"
// sugere uma precisão que a medida não tem, e ninguém tem 0,3 de artista.
function effective(v) {
  return `≈${nf.format(Math.max(1, Math.round(v)))}`;
}

// "~18 h" / "~25 min", e o horário em que libera.
function blockText(seconds) {
  const until = new Date(Date.now() + seconds * 1000);
  const span = seconds >= 5400 ? `~${Math.round(seconds / 3600)} h` : `~${Math.max(1, Math.ceil(seconds / 60))} min`;
  const at = until.toLocaleString("pt-BR", {
    weekday: until.toDateString() === new Date().toDateString() ? undefined : "short",
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${span} (até ${at})`;
}

// ── as leituras: o número vira uma frase sobre a pessoa ──────────────────────
//
// Cada escala tem duas formas do mesmo juízo: a frase, que é o que o cartão
// mostra abaixo do número, e a palavra, curta o bastante para caber grifada no
// meio do retrato. Escrever as duas à mão evita o grifo de meia linha que sai
// de encurtar a frase na marra.

const VARIETY = [
  [12, "Um gosto que não cabe numa prateleira", "muito eclético"],
  [7, "Eclético, com vários centros", "eclético"],
  [4, "Variado, em torno de alguns estilos", "variado"],
  [0, "Focado em poucos estilos", "focado"],
];

const POPULARITY = [
  [65, "Quase tudo que você ouve, muita gente ouve", "bem mainstream"],
  [45, "Mais conhecido do que obscuro", "mais pop que obscuro"],
  [25, "Entre o hit e o garimpo", "entre o hit e o garimpo"],
  [0, "Garimpo fundo, longe das paradas", "de garimpo fundo"],
];

const LOYALTY = [
  [120, "Você raramente volta ao mesmo artista"],
  [40, "Muita gente diferente, poucos favoritos fixos"],
  [15, "Um punhado de artistas sustenta o acervo"],
  [0, "Você volta sempre aos mesmos"],
];

const TEMPO = [
  [160, "Frenético", "frenético"],
  [135, "Acelerado", "acelerado"],
  [115, "Dançante", "dançante"],
  [90, "Moderado", "moderado"],
  [0, "Lento", "lento"],
];

/** A primeira linha cujo piso o valor alcança. As tabelas vêm do maior ao menor. */
function reading(table, value) {
  return table.find(([floor]) => value >= floor) ?? table[table.length - 1];
}

/**
 * O retrato em uma frase, montado dos mesmos números dos cartões abaixo.
 *
 * É a primeira coisa que se lê na página, e a única que tenta dizer o conjunto
 * — os gráficos detalham, ela resume. Cada pedaço some sozinho quando o dado
 * que o sustenta não existe, então a frase encolhe em vez de inventar.
 */
function signature({ library: lib, top_genres, decades }) {
  const chunks = [];
  const key = (text) => <b key={`${chunks.length}-${text}`}>{text}</b>;

  if (top_genres.length === 0) return null;

  chunks.push("Um gosto ", key(reading(VARIETY, lib.genre_diversity)[2]), ", ancorado em ", key(top_genres[0].label));
  if (top_genres[1]) chunks.push(" e ", key(top_genres[1].label));

  const topDecade = decades.reduce((a, b) => (b.count > (a?.count ?? -1) ? b : a), null);
  if (topDecade) chunks.push(", com o centro de gravidade nos ", key(`anos ${topDecade.decade}`));

  if (lib.avg_popularity != null) chunks.push(", ", key(reading(POPULARITY, lib.avg_popularity)[2]));
  if (lib.avg_bpm != null) chunks.push(", em andamento ", key(reading(TEMPO, lib.avg_bpm)[2]));

  chunks.push(".");
  return chunks;
}

export default function Profile() {
  const { user: sessionUser } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [starting, setStarting] = useState(false);
  const timer = useRef(null);
  const alive = useRef(true);
  const lastDone = useRef(null);

  const load = useCallback(async () => {
    try {
      const next = await api.getProfile();
      if (!alive.current) return null;
      setData(next);
      setError(null);
      return next;
    } catch (e) {
      if (!alive.current) return null;
      setError({
        // 404 aqui quase sempre é um backend antigo ainda rodando, sem a rota nova.
        message:
          e.status === 404
            ? "O backend não conhece a rota do perfil. Reinicie o backend para carregar a versão nova."
            : e.message || "Não foi possível carregar o perfil.",
        retryAfter: e.retryAfter,
      });
      return null;
    }
  }, []);

  // Enquanto a varredura roda, consulta só o progresso (barato) e recarrega o
  // painel quando uma playlist nova termina. Para sozinho no fim.
  const poll = useCallback(async () => {
    clearTimeout(timer.current);
    let progress;
    try {
      progress = await api.getProfileBuild();
    } catch {
      return;
    }
    if (!alive.current) return;
    if (progress.done !== lastDone.current || !progress.running) {
      lastDone.current = progress.done;
      await load();
    } else {
      setData((d) => (d ? { ...d, build: progress } : d));
    }
    if (alive.current && progress.running) {
      timer.current = setTimeout(poll, POLL_MS);
    }
  }, [load]);

  const build = useCallback(async () => {
    setStarting(true);
    try {
      await api.buildProfile();
    } catch {
      // Sem varredura, o painel ainda mostra o que já existe.
    } finally {
      if (alive.current) setStarting(false);
    }
    lastDone.current = null;
    poll();
  }, [poll]);

  useEffect(() => {
    alive.current = true;
    // Abrir o perfil só lê o que já existe — nenhuma varredura começa sozinha.
    // Se uma já estiver rodando (iniciada pela busca, por exemplo), acompanha.
    load().then((d) => {
      if (d?.build?.running) poll();
    });
    return () => {
      alive.current = false;
      clearTimeout(timer.current);
    };
  }, [load, poll]);

  if (error && !data) {
    return (
      <div className="container">
        <div className="error-banner" role="alert">
          <span>{error.message}</span>
          <button className="btn btn-ghost btn-sm" onClick={() => load()}>
            Tentar de novo
          </button>
        </div>
      </div>
    );
  }

  if (!data) return <ProfileSkeleton user={sessionUser} />;

  const { user, overview, coverage, stats, index, build: progress } = data;
  // `|| null` importa: com 0 segundos, `{blocked && …}` imprimiria um "0" solto na página.
  const blocked = progress.running ? null : progress.blocked_seconds || data.spotify_blocked_seconds || null;
  const name = user.display_name || sessionUser?.display_name || "Você";
  const image = user.image || sessionUser?.image;
  const partial = coverage.playlists_ready < coverage.playlists_total;
  const portrait = stats && signature(stats);

  return (
    <div className="container page-enter">
      <section className="hero profile-hero">
        {image && <div className="hero-backdrop" style={{ backgroundImage: `url(${image})` }} aria-hidden="true" />}
        {image ? (
          <img className="hero-art profile-avatar" src={image} alt="" />
        ) : (
          <div className="hero-art profile-avatar profile-avatar-empty" aria-hidden="true">
            {name.charAt(0).toUpperCase()}
          </div>
        )}
        <div className="hero-body">
          <p className="profile-kicker">Retrato do seu gosto</p>
          <h1 className="hero-title">{name}</h1>

          {portrait ? (
            <p className="profile-signature">{portrait}</p>
          ) : (
            <p className="hero-meta">O retrato aparece aqui assim que suas playlists forem analisadas.</p>
          )}

          {stats?.library.first_added && (
            <p className="profile-since">
              Ouvindo e montando playlists desde {dateFmt.format(new Date(stats.library.first_added))}.
            </p>
          )}

          <div className="stat-row">
            {stats && <Stat value={nf.format(stats.library.unique_tracks)} label="faixas no acervo" />}
            {(stats || index) && (
              <Stat
                value={nf.format(Math.max(stats?.library.unique_artists ?? 0, index?.unique_artists ?? 0))}
                label="artistas"
              />
            )}
            {stats && stats.top_genres.length > 0 && (
              <Stat value={effective(stats.library.genre_diversity)} label="gêneros efetivos" />
            )}
            {stats && !partial && <Stat value={hours(stats.library.total_duration_ms)} label="de música" />}
            {!stats && overview.playlists > 0 && <Stat value={nf.format(overview.playlists)} label="playlists" />}
          </div>
        </div>
      </section>

      <Coverage coverage={coverage} progress={progress} blocked={blocked} starting={starting} onBuild={build} />

      {stats && <Dashboard stats={stats} coverage={coverage} />}

      {index && (partial || !stats) && <IndexPanel index={index} />}

      {!stats && !index && (
        <div className="empty-state">
          <h2>{progress.running ? "Montando seu retrato" : blocked ? "O Spotify pausou o acesso" : "Nada para mostrar ainda"}</h2>
          <p>
            {progress.running
              ? "O painel aparece aqui assim que a primeira playlist terminar."
              : blocked
                ? `O Spotify suspendeu o acesso deste app por ${blockText(blocked)}. Volte depois desse horário.`
                : overview.playlists === 0
                  ? "Crie uma playlist no Spotify para ver seu retrato."
                  : "Use o botão acima para analisar suas playlists."}
          </p>
        </div>
      )}
    </div>
  );
}

function Stat({ value, label }) {
  return (
    <div className="stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}

function Coverage({ coverage, progress, blocked, starting, onBuild }) {
  const { playlists_total, playlists_ready, tracks_total, tracks_ready, playlists_stale, pending_playlists, estimated_calls } =
    coverage;
  const done = playlists_total > 0 && pending_playlists === 0;
  const share = tracks_total ? (tracks_ready / tracks_total) * 100 : 100;
  // Mesma conta do backend: ~2 s de pausa por playlist e teto de 60 por hora.
  const minutes = Math.max(1, Math.ceil((pending_playlists * 2.5) / 60));
  const eta = pending_playlists > 60 ? `mais de ${Math.floor(pending_playlists / 60)} h` : `~${minutes} min`;

  if (playlists_total === 0 && !progress.running) {
    return blocked ? (
      <div className="coverage profile-coverage">
        <p className="coverage-errors">
          O Spotify suspendeu o acesso deste app por {blockText(blocked)}. Nenhuma chamada sai até lá; o que aparece
          abaixo vem do índice da busca.
        </p>
      </div>
    ) : null;
  }

  return (
    <div className="coverage profile-coverage">
      <div className="coverage-top">
        <span className="coverage-label">
          {done ? (
            <>
              O retrato usa <b>todas as {nf.format(playlists_total)}</b> playlists com faixas.
            </>
          ) : (
            <>
              O retrato usa <b>{nf.format(playlists_ready)}</b> de <b>{nf.format(playlists_total)}</b> playlists (
              {nf.format(tracks_ready)} de {nf.format(tracks_total)} faixas)
              {playlists_stale > 0 && <>, {playlists_stale} com dados de antes da última mudança</>}.
            </>
          )}
        </span>
        {progress.running ? (
          <span className="btn btn-ghost btn-sm" aria-disabled="true">
            Analisando
          </span>
        ) : (
          pending_playlists > 0 &&
          !blocked && (
            <button
              className="btn btn-sm"
              onClick={onBuild}
              disabled={starting}
              title="Lê do Spotify só as playlists que faltam ou mudaram, uma por vez"
            >
              Analisar {pending_playlists === 1 ? "a que falta" : `as ${nf.format(pending_playlists)} que faltam`}
            </button>
          )
        )}
      </div>

      {!done && (
        <span className="coverage-bar" aria-hidden="true">
          <span className="coverage-bar-fill" style={{ width: `${share}%` }} />
        </span>
      )}

      {!progress.running && !blocked && pending_playlists > 0 && (
        <p className="coverage-note">
          Custa ~{nf.format(estimated_calls)} chamadas ao Spotify e leva {eta}: uma playlist por vez, com pausas, para
          não esbarrar no limite de novo. Você pode sair da página; a análise continua.
        </p>
      )}

      {progress.running && (
        <div className="coverage-running" role="status">
          <span className="typing-dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          {progress.waiting_seconds ? (
            <span>
              Pausa de {progress.waiting_seconds > 90 ? `${Math.round(progress.waiting_seconds / 60)} min` : `${Math.round(progress.waiting_seconds)} s`}{" "}
              para respeitar o limite…
            </span>
          ) : (
            <>
              <span>
                {progress.done} de {progress.total}
              </span>
              {progress.current && <span className="coverage-current">{progress.current}</span>}
            </>
          )}
        </div>
      )}

      {blocked && (
        <p className="coverage-errors">
          O Spotify suspendeu o acesso deste app por {blockText(blocked)}. Nenhuma chamada sai até lá; o que já foi
          analisado continua no painel.
        </p>
      )}
      {progress.errors.length > 0 && !progress.running && (
        <p className="coverage-errors">
          {progress.errors.length} {progress.errors.length === 1 ? "playlist falhou" : "playlists falharam"}:{" "}
          {progress.errors.slice(0, 3).join("; ")}
        </p>
      )}
    </div>
  );
}

/** Artistas e estilos do índice da busca: o acervo inteiro, sem chamar o Spotify. */
function IndexPanel({ index }) {
  return (
    <>
      <header className="section-head">
        <h2>Do seu acervo indexado</h2>
        <p className="panel-sub">
          {nf.format(index.tracks)} faixas que a busca já conhece, de todas as playlists indexadas. Mostra quem e o
          quê aparece mais; a época, o andamento e a mudança do gosto só vêm com a análise completa.
        </p>
      </header>
      <div className="charts-grid">
        <DistributionBarChart
          data={index.top_artists.map((a) => ({ label: a.name, count: a.tracks }))}
          limit={12}
          title="Artistas"
          subtitle="Faixas de cada artista no índice"
          foot={null}
        />
        <DistributionBarChart
          data={index.top_tags.slice(0, 12)}
          total={index.tracks}
          limit={12}
          title="Gêneros e estilos"
          subtitle="Tags do Last.fm, do artista e da faixa juntas"
          foot={null}
        />
      </div>
    </>
  );
}

function Dashboard({ stats, coverage }) {
  const { library: lib, top_genres, top_artists, top_tags, decades, taste_timeline, popularity_bands, deep_cuts, playlists } =
    stats;

  const topGenre = top_genres[0];
  const topDecade = decades.reduce((a, b) => (b.count > (a?.count ?? -1) ? b : a), null);
  const decadeTotal = decades.reduce((s, d) => s + d.count, 0);

  // A cor segue o gênero, não a posição na lista: o mesmo gênero é a mesma cor
  // na linha do gosto e nas barras. Fora do topo, o cinza neutro — são muitos
  // para ter nome de cor, e inventar uma sétima quebraria a paleta.
  const genreColor = useMemo(() => {
    const map = new Map(top_genres.slice(0, TASTE_SERIES).map((g, i) => [g.label, SERIES[i]]));
    return (label) => map.get(label) ?? NEUTRAL;
  }, [top_genres]);

  const decadeData = useMemo(
    () => decades.map((d) => ({ key: d.decade, label: `${String(d.decade).slice(2)}s`, tooltip: `Anos ${d.decade}`, count: d.count })),
    [decades],
  );

  const popularityData = useMemo(
    () =>
      popularity_bands.map((b) => ({
        key: b.label,
        label: b.label,
        tooltip: `${b.label} (${b.from}–${b.to - 1} de 100)`,
        count: b.count,
      })),
    [popularity_bands],
  );

  const timelineYears = taste_timeline?.years ?? [];

  return (
    <>
      <section className="facet-grid" aria-label="As facetas do seu gosto">
        {topGenre && (
          <Facet
            kicker="Gênero dominante"
            value={topGenre.label}
            sub={`${pct(topGenre.count, lib.unique_tracks)} das faixas do acervo`}
            swatch={genreColor(topGenre.label)}
          />
        )}
        <Facet
          kicker="Variedade"
          value={`${effective(lib.genre_diversity)} gêneros`}
          sub={reading(VARIETY, lib.genre_diversity)[1]}
          hint="Número efetivo de gêneros: quantos gêneros igualmente frequentes dariam a mesma variedade."
        />
        {topDecade && (
          <Facet
            kicker="Época"
            value={`Anos ${topDecade.decade}`}
            sub={`${pct(topDecade.count, decadeTotal)} das faixas com data${lib.median_release_year ? `; metade é de ${lib.median_release_year} ou antes` : ""}`}
          />
        )}
        <Facet
          kicker="Fidelidade"
          value={`${effective(lib.artist_diversity)} artistas`}
          sub={reading(LOYALTY, lib.artist_diversity)[1]}
          hint="Número efetivo de artistas: quantos artistas igualmente presentes dariam o mesmo espalhamento."
        />
        {lib.avg_popularity != null && (
          <Facet
            kicker="No radar"
            value={`${Math.round(lib.avg_popularity)} de 100`}
            sub={`${reading(POPULARITY, lib.avg_popularity)[1]}, em ${nf.format(lib.popularity_known)} faixas`}
            spectrum={{ value: lib.avg_popularity / 100, ends: ["garimpo", "hit"] }}
            hint="Popularidade média das suas faixas no Spotify, de 0 a 100."
          />
        )}
        {lib.avg_bpm != null && (
          <Facet
            kicker="Andamento"
            value={`${Math.round(lib.avg_bpm)} BPM`}
            sub={`${reading(TEMPO, lib.avg_bpm)[1]}, em ${nf.format(lib.bpm_known)} faixas com BPM conhecido`}
            spectrum={{ value: (lib.avg_bpm - 60) / 120, ends: ["60", "180"] }}
            hint="O BPM vem do Deezer e só existe para as playlists que você já abriu ou que a busca indexou."
          />
        )}
      </section>

      <div className="charts-grid">
        <DistributionBarChart
          // O backend manda só o topo; um "outros" aqui somaria só o resto desse topo.
          data={top_genres.slice(0, 10)}
          total={lib.unique_tracks}
          limit={10}
          title="Do que seu gosto é feito"
          subtitle={`Gêneros dos artistas no Last.fm, sobre ${nf.format(lib.unique_tracks)} faixas únicas`}
          colorFor={genreColor}
          shareOf="do acervo"
          foot={
            lib.tracks_with_genre < lib.unique_tracks
              ? `${nf.format(lib.unique_tracks - lib.tracks_with_genre)} faixas ficaram sem gênero. Uma faixa pode ter vários gêneros.`
              : "Uma faixa pode ter vários gêneros, então a soma passa de 100%."
          }
        />
        <DistributionBarChart
          data={top_artists.map((a) => ({ label: a.name, count: a.tracks, playlists: a.playlists }))}
          limit={12}
          title="Os nomes que se repetem"
          subtitle="Faixas únicas de cada artista nas suas playlists"
          detailFor={(r) => `em ${r.playlists} ${r.playlists === 1 ? "playlist" : "playlists"}`}
          foot={null}
        />
      </div>

      {timelineYears.length >= 2 && (
        <section className="panel panel-flow">
          <header className="panel-head">
            <h3>Como seu gosto mudou</h3>
            <p className="panel-sub">
              As faixas que entraram nas suas playlists a cada ano. Cada linha é um dos gêneros que você mais escolhe; a
              coluna ao fundo é o total do ano. Passe o mouse para ver o ano; clique na legenda para isolar um gênero.
            </p>
          </header>
          <TasteTimeline genres={taste_timeline.genres} years={timelineYears} />
          <p className="panel-foot muted">
            Aqui conta cada vez que uma faixa entrou numa playlist, e só as que têm data. Uma faixa com vários desses
            gêneros é repartida entre eles, por isso os números não batem com os de “Do que seu gosto é feito”.
          </p>
        </section>
      )}

      <div className={top_tags.length > 0 ? "charts-grid" : undefined}>
        <section className="panel">
          <header className="panel-head">
            <h3>De que época você ouve</h3>
            <p className="panel-sub">Pelo ano de lançamento do álbum.</p>
          </header>
          <ColumnChart data={decadeData} ariaLabel="Faixas por década de lançamento" />
          {lib.oldest_track && (
            <p className="panel-foot muted">
              A mais antiga: <Link to={`/faixa/${lib.oldest_track.id}`}>{lib.oldest_track.name}</Link>, de{" "}
              {lib.oldest_track.artists.join(", ")} ({lib.oldest_track.year}).
            </p>
          )}
        </section>
        {top_tags.length > 0 && (
          <DistributionBarChart
            data={top_tags.slice(0, 10)}
            total={lib.unique_tracks}
            limit={10}
            title="O gosto em detalhe"
            subtitle="Tags das próprias faixas que não aparecem entre os gêneros"
            shareOf="do acervo"
            foot={null}
          />
        )}
      </div>

      {popularityData.length > 0 && (
        <section className="panel">
          <header className="panel-head">
            <h3>Entre o hit e o garimpo</h3>
            <p className="panel-sub">
              Quantas faixas suas caem em cada nível de popularidade no Spotify, das desconhecidas às que todo mundo
              ouve.
            </p>
          </header>
          <ColumnChart data={popularityData} ariaLabel="Faixas por nível de popularidade no Spotify" />
        </section>
      )}

      {deep_cuts.length > 0 && (
        <section className="panel">
          <header className="panel-head">
            <h3>Seus garimpos</h3>
            <p className="panel-sub">
              As faixas mais fora do radar que você guardou: as de menor popularidade no Spotify, entre as suas.
            </p>
          </header>
          <ol className="cut-list">
            {deep_cuts.map((t) => (
              <li key={t.id}>
                <Link to={`/faixa/${t.id}`} className="cut-row">
                  {t.image ? <img src={t.image} alt="" loading="lazy" /> : <span className="cut-art-empty" aria-hidden="true" />}
                  <span className="cut-text">
                    <span className="cut-name">{t.name}</span>
                    <span className="cut-sub">
                      {t.artists.join(", ")}
                      {t.genre && <span className="cut-genre">{t.genre}</span>}
                    </span>
                  </span>
                  <span className="cut-score" title="Popularidade no Spotify, de 0 a 100">
                    <span className="tabular">{t.popularity}</span>
                    <span className="cut-score-unit">/100</span>
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        </section>
      )}

      <PlaylistTable rows={playlists} partial={coverage.playlists_ready < coverage.playlists_total} />
    </>
  );
}

/**
 * Uma faceta do gosto: o rótulo do eixo, a leitura em palavras e o número que
 * a sustenta. O valor grande é uma frase, não um número solto — "garimpo
 * fundo" diz mais que "23 de 100", e o número fica logo abaixo para quem quiser.
 */
function Facet({ kicker, value, sub, hint, spectrum, swatch }) {
  return (
    <div className="facet" title={hint}>
      <span className="facet-kicker">{kicker}</span>
      <span className="facet-value">
        {swatch && <span className="viz-swatch facet-swatch" style={{ background: swatch }} aria-hidden="true" />}
        {value}
      </span>
      {spectrum && (
        <span className="spectrum" aria-hidden="true">
          <span className="spectrum-track">
            <span className="spectrum-dot" style={{ left: `${Math.max(0, Math.min(1, spectrum.value)) * 100}%` }} />
          </span>
          <span className="spectrum-ends">
            <span>{spectrum.ends[0]}</span>
            <span>{spectrum.ends[1]}</span>
          </span>
        </span>
      )}
      {sub && <span className="facet-sub">{sub}</span>}
    </div>
  );
}

const COLUMNS = [
  { key: "name", label: "Playlist", numeric: false },
  { key: "tracks", label: "Faixas", numeric: true },
  { key: "artists", label: "Artistas", numeric: true },
  { key: "genre_diversity", label: "Variedade", numeric: true, title: "Número efetivo de gêneros" },
];

function PlaylistTable({ rows, partial }) {
  const [sort, setSort] = useState({ key: "tracks", dir: -1 });

  const sorted = useMemo(() => {
    const out = [...rows];
    out.sort((a, b) => {
      const va = a[sort.key];
      const vb = b[sort.key];
      if (typeof va === "string") return va.localeCompare(vb, "pt-BR") * sort.dir;
      return ((va ?? 0) - (vb ?? 0)) * sort.dir;
    });
    return out;
  }, [rows, sort]);

  // Destaques só entre playlists com faixas suficientes para a variedade dizer algo.
  const eligible = rows.filter((r) => r.tracks >= 10 && r.top_genre);
  const eclectic = eligible.reduce((a, b) => (b.genre_diversity > (a?.genre_diversity ?? -1) ? b : a), null);
  const focused = eligible.reduce((a, b) => (b.genre_diversity < (a?.genre_diversity ?? Infinity) ? b : a), null);

  return (
    <section className="panel">
      <header className="panel-head">
        <h3>Cada playlist é um lado seu</h3>
        <p className="panel-sub">
          {eclectic && focused && eclectic.id !== focused.id ? (
            <>
              A mais eclética é <b>{eclectic.name}</b> ({effective(eclectic.genre_diversity)} gêneros efetivos); a mais
              focada é <b>{focused.name}</b>, quase toda {focused.top_genre}.
            </>
          ) : (
            "Clique no título de uma coluna para ordenar."
          )}
          {partial && " Playlists ainda não analisadas entram conforme a varredura avança."}
        </p>
      </header>
      <div className="pl-table-scroll">
        <table className="pl-table">
          <thead>
            <tr>
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  className={c.numeric ? "num" : undefined}
                  aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
                >
                  <button
                    type="button"
                    title={c.title}
                    onClick={() =>
                      setSort((s) => (s.key === c.key ? { key: c.key, dir: -s.dir } : { key: c.key, dir: c.numeric ? -1 : 1 }))
                    }
                  >
                    {c.label}
                    {sort.key === c.key && <span aria-hidden="true">{sort.dir === 1 ? " ↑" : " ↓"}</span>}
                  </button>
                </th>
              ))}
              <th>Gênero principal</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.id}>
                <td>
                  <Link to={`/playlists/${r.id}`} className="pl-cell-name">
                    {r.image ? <img src={r.image} alt="" loading="lazy" /> : <span className="pl-art-empty" aria-hidden="true" />}
                    <span>{r.name}</span>
                  </Link>
                </td>
                <td className="num">{nf.format(r.tracks)}</td>
                <td className="num">{nf.format(r.artists)}</td>
                <td className="num">{r.top_genre ? decimal(r.genre_diversity) : "—"}</td>
                <td className="pl-genre">{r.top_genre ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ProfileSkeleton({ user }) {
  return (
    <div className="container" aria-busy="true">
      <section className="hero profile-hero">
        {user?.image ? (
          <img className="hero-art profile-avatar" src={user.image} alt="" />
        ) : (
          <div className="hero-art profile-avatar skeleton" />
        )}
        <div className="hero-body">
          <p className="profile-kicker">Retrato do seu gosto</p>
          <h1 className="hero-title">{user?.display_name ?? "…"}</h1>
          <div className="stat-row">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="stat">
                <span className="skeleton skeleton-stat" />
                <span className="skeleton skeleton-line skeleton-line-short" />
              </div>
            ))}
          </div>
        </div>
      </section>
      <div className="facet-grid">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="facet">
            <span className="skeleton skeleton-line skeleton-line-short" />
            <span className="skeleton skeleton-stat" />
          </div>
        ))}
      </div>
    </div>
  );
}
