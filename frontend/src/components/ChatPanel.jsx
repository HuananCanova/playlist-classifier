import React, { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../api.js";

// O que cada ferramenta do backend está fazendo, em português.
const TOOL_LABELS = {
  visao_geral: "Analisando várias playlists em paralelo…",
  listar_playlists: "Consultando suas playlists…",
  analisar_playlist: "Analisando os gêneros da playlist…",
  analisar_esta_playlist: "Analisando esta playlist…",
};

function Dots() {
  return (
    <span className="typing-dots" aria-hidden="true">
      <span />
      <span />
      <span />
    </span>
  );
}

/**
 * O chat, usado em dois lugares: a aba geral (sem `playlistId`, enxerga toda a
 * conta) e a página de detalhe (com `playlistId`, restrito àquela playlist).
 */
export default function ChatPanel({ playlistId = null, suggestions = [], compact = false }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [activity, setActivity] = useState(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, activity]);

  async function send(text) {
    const question = text.trim();
    if (!question || streaming) return;

    // Turnos que falharam ficam com conteúdo vazio. Reenviá-los faria o backend
    // recusar a requisição inteira (o schema exige conteúdo), o que travava a
    // conversa de vez depois do primeiro erro.
    const usable = messages.filter((m) => m.content && !m.error);
    const history = [...usable, { role: "user", content: question }];

    setInput("");
    setStreaming(true);
    setActivity(null);
    setMessages([...messages, { role: "user", content: question }, { role: "assistant", content: "" }]);

    try {
      const res = await api.chatStream(history, playlistId);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Um evento SSE termina em linha em branco; o resto fica no buffer.
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;

          let evt;
          try {
            evt = JSON.parse(line.slice(6));
          } catch {
            continue;
          }

          if (evt.type === "text") {
            setActivity(null);
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              next[next.length - 1] = { role: "assistant", content: last.content + evt.delta };
              return next;
            });
          } else if (evt.type === "tool") {
            setActivity(TOOL_LABELS[evt.name] || "Buscando dados…");
          } else if (evt.type === "error") {
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = { role: "assistant", content: "", error: evt.message };
              return next;
            });
          }
        }
      }
    } catch {
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = {
          role: "assistant",
          content: "",
          error: "A conexão com o chat caiu. Tente de novo.",
        };
        return next;
      });
    } finally {
      setStreaming(false);
      setActivity(null);
    }
  }

  return (
    <div className={`chat${compact ? " chat-compact" : ""}`}>
      <div className="chat-thread">
        {messages.length === 0 && suggestions.length > 0 && (
          <div className="chat-empty">
            <p className="muted">Comece por uma dessas:</p>
            <div className="chat-suggestions">
              {suggestions.map((s) => (
                <button key={s} className="suggestion" onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`bubble bubble-${m.role}`}>
            {m.error ? (
              <span className="bubble-error">{m.error}</span>
            ) : m.content ? (
              m.role === "assistant" ? (
                <div className="markdown">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                </div>
              ) : (
                m.content
              )
            ) : streaming && i === messages.length - 1 ? (
              <Dots />
            ) : null}
          </div>
        ))}

        {activity && (
          <div className="chat-activity">
            <Dots />
            {activity}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form
        className="chat-composer"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <input
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={playlistId ? "Pergunte sobre esta playlist…" : "Pergunte sobre suas playlists…"}
          disabled={streaming}
          aria-label="Sua pergunta"
        />
        <button className="btn" type="submit" disabled={streaming || !input.trim()}>
          {streaming ? "Pensando…" : "Enviar"}
        </button>
      </form>
    </div>
  );
}
