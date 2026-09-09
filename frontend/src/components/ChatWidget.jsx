import React, { useEffect, useRef, useState } from "react";
import ChatPanel from "./ChatPanel.jsx";

const COPY = {
  playlist: {
    fabLabel: "Perguntar",
    title: "Perguntar sobre esta playlist",
    subtitle: (name) =>
      name
        ? `Só sobre “${name}” — para outra playlist, abra-a e use o chat dali.`
        : "Escopo: esta playlist",
    ariaFab: "Abrir o chat sobre esta playlist",
    ariaDrawer: (name) => `Chat sobre a playlist ${name || ""}`,
  },
  track: {
    fabLabel: "Perguntar",
    title: "Perguntar sobre esta faixa",
    subtitle: (name) =>
      name
        ? `Só sobre “${name}” — para a playlist inteira, volte e use o chat dali.`
        : "Escopo: esta faixa",
    ariaFab: "Abrir o chat sobre esta faixa",
    ariaDrawer: (name) => `Chat sobre a faixa ${name || ""}`,
  },
};

export default function ChatWidget({
  scope = "playlist",
  playlistId = null,
  trackId = null,
  subjectName = "",
  suggestions = [],
}) {
  const [open, setOpen] = useState(false);
  const [everOpened, setEverOpened] = useState(false);
  const panelRef = useRef(null);
  const triggerRef = useRef(null);
  const copy = COPY[scope] ?? COPY.playlist;

  useEffect(() => {
    if (open) setEverOpened(true);
  }, [open]);

  useEffect(() => {
    if (!open) return;

    const onKeyDown = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);

    panelRef.current?.querySelector("input")?.focus();

    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  useEffect(() => {
    if (!open && everOpened) triggerRef.current?.focus();
  }, [open, everOpened]);

  return (
    <>
      <button
        ref={triggerRef}
        className={`chat-fab${open ? " chat-fab-hidden" : ""}`}
        onClick={() => setOpen(true)}
        aria-label={copy.ariaFab}
        aria-expanded={open}
        tabIndex={open ? -1 : 0}
      >
        <ChatIcon />
        <span className="chat-fab-label">{copy.fabLabel}</span>
      </button>

      <aside
        ref={panelRef}
        className={`chat-drawer${open ? " is-open" : ""}`}
        role="complementary"
        aria-label={copy.ariaDrawer(subjectName)}
        {...(open ? {} : { inert: "" })}
      >
        <header className="chat-drawer-head">
          <div className="chat-drawer-title">
            <h3>{copy.title}</h3>
            <p className="panel-sub">{copy.subtitle(subjectName)}</p>
          </div>
          <button
            className="chat-drawer-close"
            onClick={() => setOpen(false)}
            aria-label="Fechar o chat"
          >
            <CloseIcon />
          </button>
        </header>

        {everOpened && (
          <ChatPanel
            playlistId={playlistId}
            trackId={trackId}
            compact
            suggestions={suggestions}
          />
        )}
      </aside>
    </>
  );
}

function ChatIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M18 6 6 18M6 6l12 12"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}
