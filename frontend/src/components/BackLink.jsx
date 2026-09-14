import React from "react";
import { Link } from "react-router-dom";

export default function BackLink({ to, onClick }) {
  const content = (
    <>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M15 18l-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Voltar
    </>
  );
  return to ? (
    <Link to={to} className="back-link">
      {content}
    </Link>
  ) : (
    <button type="button" className="back-link" onClick={onClick}>
      {content}
    </button>
  );
}
