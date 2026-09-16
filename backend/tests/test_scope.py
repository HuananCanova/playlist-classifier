"""O escopo do chat é a garantia de custo do projeto — vale testá-la de verdade.

A promessa é: uma conversa fala de uma playlist OU de uma faixa, nunca da conta
inteira. Ela não é feita pelo prompt (que o modelo pode ignorar) e sim pela
forma das ferramentas: nenhuma delas aceita um id, então não há como pedir outra
playlist. Estes testes cobrem essa amarração.
"""
import pytest
from pydantic import ValidationError

from app.ai_tools import build_tools
from app.chat import ChatRequest


def test_escopo_exige_exatamente_um():
    with pytest.raises(ValueError):
        build_tools("token", "dono")
    with pytest.raises(ValueError):
        build_tools("token", "dono", playlist_id="p", track_id="t")


def test_ferramentas_da_playlist_nao_aceitam_id():
    """Nenhuma ferramenta pode receber um id de playlist ou faixa.

    `buscar_nesta_playlist` recebe `consulta` — texto livre, não um ponteiro
    para outro recurso. Se um id aparecer aqui, o escopo virou sugestão.
    """
    tools = build_tools("token", "dono", playlist_id="p1")
    assert [t.name for t in tools] == [
        "analisar_esta_playlist",
        "buscar_nesta_playlist",
        "grupos_desta_playlist",
    ]
    for tool in tools:
        propriedades = set(tool.parameters.get("properties", {}))
        assert not propriedades & {"playlist_id", "track_id", "id"}


def test_ferramentas_da_faixa_nao_aceitam_id():
    tools = build_tools("token", "dono", track_id="t1")
    assert [t.name for t in tools] == ["analisar_esta_faixa", "faixas_parecidas"]
    for tool in tools:
        assert tool.parameters.get("properties") == {}


def test_request_recusa_escopo_ambiguo():
    mensagens = [{"role": "user", "content": "oi"}]

    with pytest.raises(ValidationError):
        ChatRequest(messages=mensagens)
    with pytest.raises(ValidationError):
        ChatRequest(messages=mensagens, playlist_id="p", track_id="t")

    assert ChatRequest(messages=mensagens, playlist_id="p").track_id is None
    assert ChatRequest(messages=mensagens, track_id="t").playlist_id is None


def test_request_limita_historico():
    """O teto de histórico é o outro controle de custo: sem ele, uma conversa
    longa reenvia tudo a cada turno."""
    uma = {"role": "user", "content": "oi"}
    with pytest.raises(ValidationError):
        ChatRequest(messages=[uma] * 21, playlist_id="p")
