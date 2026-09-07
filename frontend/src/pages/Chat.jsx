import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import ChatPanel from "../components/ChatPanel.jsx";

const SUGGESTIONS = [
  "O que minhas playlists dizem sobre meu gosto musical?",
  "Qual é o gênero dominante nas minhas playlists?",
  "Qual playlist tem a mistura mais eclética?",
];

export default function Chat() {
  const [available, setAvailable] = useState(null);

  useEffect(() => {
    api
      .chatStatus()
      .then((s) => setAvailable(s.available))
      .catch(() => setAvailable(false));
  }, []);

  if (available === false) {
    return (
      <div className="container">
        <h2 className="page-title">Chat</h2>
        <div className="note" style={{ marginTop: 16 }}>
          <p style={{ margin: "0 0 10px" }}>
            O chat precisa de uma chave de IA no <code>backend/.env</code>, e do backend
            reiniciado depois de adicioná-la.
          </p>
          <p style={{ margin: 0 }}>
            Com{" "}
            <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer">
              Claude
            </a>
            : <code>CHAT_PROVIDER=anthropic</code> e <code>ANTHROPIC_API_KEY</code>. Com{" "}
            <a href="https://console.groq.com/keys" target="_blank" rel="noreferrer">
              Groq
            </a>
            : <code>CHAT_PROVIDER=groq</code> e <code>GROQ_API_KEY</code>.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="container chat-page">
      <div className="page-head">
        <div>
          <h2 className="page-title">Chat</h2>
          <p className="muted page-sub">
            Pergunte sobre suas playlists — a IA consulta os dados reais
          </p>
        </div>
      </div>

      <ChatPanel suggestions={SUGGESTIONS} />
    </div>
  );
}
