import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

// O que cada ferramenta do backend está fazendo, em português.
const TOOL_LABELS = {
  listar_playlists: "Consultando suas playlists…",
  analisar_playlist: "Analisando os gêneros da playlist…",
};

const SUGGESTIONS = [
  "Qual é o gênero dominante nas minhas playlists?",
  "O que minhas playlists dizem sobre meu gosto musical?",
  "Qual playlist tem a mistura mais eclética?",
];

export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [activity, setActivity] = useState(null);
  const [available, setAvailable] = useState(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    api
      .chatStatus()
      .then((s) => setAvailable(s.available))
      .catch(() => setAvailable(false));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, activity]);

  async function send(text) {
    const question = text.trim();
    if (!question || streaming) return;

    const history = [...messages, { role: "user", content: question }];
    setMessages(history);
    setInput("");
    setStreaming(true);
    setActivity(null);

    // Espaço para a resposta, preenchido conforme os deltas chegam.
    setMessages([...history, { role: "assistant", content: "" }]);

    try {
      const res = await api.chatStream(history);
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
              next[next.length - 1] = {
                role: "assistant",
                content: next[next.length - 1].content + evt.delta,
              };
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

  if (available === false) {
    return (
      <div className="container">
        <h2 className="page-title">Chat</h2>
        <div className="note" style={{ marginTop: 16 }}>
          O chat precisa de uma <code>ANTHROPIC_API_KEY</code> no <code>backend/.env</code>.
          Crie uma em{" "}
          <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer">
            console.anthropic.com
          </a>{" "}
          e reinicie o backend.
        </div>
      </div>
    );
  }

  return (
    <div className="container chat-page">
      <div className="page-head">
        <div>
          <h2 className="page-title">Chat</h2>
          <p className="muted page-sub">Pergunte sobre suas playlists — a IA consulta os dados reais</p>
        </div>
      </div>

      <div className="chat-thread">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p className="muted">Comece por uma dessas:</p>
            <div className="chat-suggestions">
              {SUGGESTIONS.map((s) => (
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
            ) : (
              m.content || (streaming && i === messages.length - 1 ? <Dots /> : null)
            )}
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
          placeholder="Pergunte sobre suas playlists…"
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

function Dots() {
  return (
    <span className="typing-dots" aria-hidden="true">
      <span />
      <span />
      <span />
    </span>
  );
}
