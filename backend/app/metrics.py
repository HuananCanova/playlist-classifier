"""Registro do que cada turno de chat custou.

O app suporta dois provedores, e até aqui a única forma de compará-los era ler
as respostas e formar uma opinião. Isto torna a comparação um número: tokens,
tempo até o primeiro texto, tempo total e quantas ferramentas o modelo chamou
para chegar na resposta.

Fica em memória, num anel de tamanho fixo. Não é um sistema de observabilidade
— é o suficiente para responder "o Groq está mesmo saindo mais barato?" sem
subir um Prometheus ao lado de um app local.
"""
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from threading import Lock

MAX_TURNOS = 200


@dataclass
class TurnMetrics:
    """Um turno: da pergunta do usuário até o agente parar de falar."""

    provider: str
    model: str
    scope: str  # "playlist" ou "track"
    tools_called: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    # Tempo até o primeiro pedaço de texto chegar ao navegador. É o que o
    # usuário percebe como "demorou", separado do tempo total.
    ttft_seconds: float | None = None
    total_seconds: float | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)

    _t0: float = field(default_factory=time.perf_counter, repr=False)

    def mark_first_text(self) -> None:
        if self.ttft_seconds is None:
            self.ttft_seconds = round(time.perf_counter() - self._t0, 3)

    def mark_tool(self, name: str) -> None:
        self.tools_called.append(name)

    def finish(self, error: str | None = None) -> None:
        self.total_seconds = round(time.perf_counter() - self._t0, 3)
        self.error = error
        _record(self)


_turnos: deque[TurnMetrics] = deque(maxlen=MAX_TURNOS)
_lock = Lock()


def _record(turno: TurnMetrics) -> None:
    with _lock:
        _turnos.append(turno)


def recent(limit: int = 50) -> list[dict]:
    with _lock:
        turnos = list(_turnos)[-limit:]
    saida = []
    for t in reversed(turnos):
        d = asdict(t)
        d.pop("_t0", None)
        saida.append(d)
    return saida


def summary() -> dict:
    """Agregado por provedor — a comparação que motivou o arquivo."""
    with _lock:
        turnos = list(_turnos)

    if not turnos:
        return {"turnos": 0, "por_provedor": {}}

    por: dict[str, dict] = {}
    for t in turnos:
        p = por.setdefault(
            t.provider,
            {"turnos": 0, "erros": 0, "input_tokens": 0, "output_tokens": 0,
             "ttfts": [], "totais": [], "ferramentas": 0},
        )
        p["turnos"] += 1
        p["erros"] += 1 if t.error else 0
        p["input_tokens"] += t.input_tokens
        p["output_tokens"] += t.output_tokens
        p["ferramentas"] += len(t.tools_called)
        if t.ttft_seconds is not None:
            p["ttfts"].append(t.ttft_seconds)
        if t.total_seconds is not None:
            p["totais"].append(t.total_seconds)

    def mediana(valores: list[float]) -> float | None:
        if not valores:
            return None
        ordenados = sorted(valores)
        meio = len(ordenados) // 2
        if len(ordenados) % 2:
            return round(ordenados[meio], 3)
        return round((ordenados[meio - 1] + ordenados[meio]) / 2, 3)

    return {
        "turnos": len(turnos),
        "por_provedor": {
            nome: {
                "turnos": p["turnos"],
                "erros": p["erros"],
                "input_tokens": p["input_tokens"],
                "output_tokens": p["output_tokens"],
                # Mediana, não média: um turno lento distorce a média e some na
                # mediana, e é a experiência típica que interessa aqui.
                "ttft_mediano": mediana(p["ttfts"]),
                "total_mediano": mediana(p["totais"]),
                "ferramentas_por_turno": round(p["ferramentas"] / p["turnos"], 2),
            }
            for nome, p in por.items()
        },
    }


def reset() -> None:
    """Zera o histórico. Só usado nos testes."""
    with _lock:
        _turnos.clear()
