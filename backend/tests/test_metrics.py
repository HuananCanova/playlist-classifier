"""O registro de custo por turno."""
from app import metrics


def setup_function():
    metrics.reset()


def test_resume_por_provedor():
    for provider, tokens in (("groq", 100), ("groq", 200), ("anthropic", 500)):
        t = metrics.TurnMetrics(provider=provider, model="m", scope="playlist")
        t.mark_tool("analisar_esta_playlist")
        t.mark_first_text()
        t.input_tokens = tokens
        t.output_tokens = 10
        t.finish()

    resumo = metrics.summary()
    assert resumo["turnos"] == 3
    assert resumo["por_provedor"]["groq"]["turnos"] == 2
    assert resumo["por_provedor"]["groq"]["input_tokens"] == 300
    assert resumo["por_provedor"]["anthropic"]["input_tokens"] == 500
    assert resumo["por_provedor"]["groq"]["ferramentas_por_turno"] == 1.0


def test_conta_erros_sem_perder_o_turno():
    t = metrics.TurnMetrics(provider="groq", model="m", scope="track")
    t.finish(error="estourou")

    resumo = metrics.summary()
    assert resumo["por_provedor"]["groq"]["erros"] == 1
    # Um turno que falhou sem emitir texto não tem TTFT — e isso não pode virar
    # um zero, que se confundiria com "respondeu instantaneamente".
    assert resumo["por_provedor"]["groq"]["ttft_mediano"] is None


def test_mantem_so_os_ultimos_turnos():
    for _ in range(metrics.MAX_TURNOS + 25):
        metrics.TurnMetrics(provider="groq", model="m", scope="playlist").finish()
    assert metrics.summary()["turnos"] == metrics.MAX_TURNOS


def test_ttft_e_o_primeiro_texto_so():
    t = metrics.TurnMetrics(provider="groq", model="m", scope="playlist")
    t.mark_first_text()
    primeiro = t.ttft_seconds
    t.mark_first_text()
    assert t.ttft_seconds == primeiro
