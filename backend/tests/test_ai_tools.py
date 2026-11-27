"""O que a ferramenta da faixa entrega ao modelo sobre selo e subgênero."""
import json

from app import ai_tools
from app.models import EvidenceLine, LabelRef, SubgenreShare, TrackDetail


def _detail(**extra) -> TrackDetail:
    return TrackDetail(
        track_id="t1",
        name="Faixa",
        artists=["Artista"],
        duration_ms=360_000,
        tags=["techno"],
        genre="electronic",
        **extra,
    )


def _patch(monkeypatch, detail: TrackDetail) -> None:
    async def fake(access_token, track_id):
        return detail

    monkeypatch.setattr(ai_tools, "build_track_detail", fake)


async def test_selo_no_mapa_traz_fatias_nota_e_fonte(monkeypatch):
    _patch(
        monkeypatch,
        _detail(
            label="Ostgut Ton",
            label_info=LabelRef(
                name="Ostgut Ton",
                nota="Selo do Berghain.",
                fonte="https://exemplo/ostgut",
                shares=[SubgenreShare(label="techno", share=0.7), SubgenreShare(label="house", share=0.3)],
            ),
            subgenre_lean="techno",
            subgenre_unsure=True,
            subgenre_blend=[SubgenreShare(label="techno", share=0.7)],
            subgenre_evidence=[EvidenceLine(source="label", says="techno", detail="Ostgut Ton")],
        ),
    )
    dados = json.loads(await ai_tools.analisar_faixa_json("tok", "t1"))

    assert dados["selo"] == {
        "nome": "Ostgut Ton",
        "no_mapa": True,
        "nome_no_mapa": "Ostgut Ton",
        "subgeneros": [{"subgenero": "techno", "fatia": 0.7}, {"subgenero": "house", "fatia": 0.3}],
        "nota": "Selo do Berghain.",
        "fonte": "https://exemplo/ostgut",
    }
    assert dados["genero"] == "electronic"
    assert dados["subgenero"] is None
    assert dados["inclinacao"] == "techno"
    assert dados["incerto"] is True
    assert dados["mistura"] == [{"subgenero": "techno", "fatia": 0.7}]
    assert dados["evidencia"] == [{"fonte": "label", "aponta": "techno", "detalhe": "Ostgut Ton"}]


async def test_selo_fora_do_mapa_so_tem_o_nome(monkeypatch):
    _patch(monkeypatch, _detail(label="Selo Qualquer"))
    selo = json.loads(await ai_tools.analisar_faixa_json("tok", "t1"))["selo"]

    assert selo["nome"] == "Selo Qualquer"
    assert selo["no_mapa"] is False
    assert selo["nota"] is None
    assert selo["fonte"] is None
    assert selo["subgeneros"] == []


async def test_sem_selo_vira_null(monkeypatch):
    _patch(monkeypatch, _detail())
    dados = json.loads(await ai_tools.analisar_faixa_json("tok", "t1"))

    assert dados["selo"] is None
    assert dados["evidencia"] == []


def test_prompt_da_faixa_explica_o_selo():
    prompt = ai_tools.system_prompt(track_id="t1")
    assert "catálogo do lançamento" in prompt
    assert "no_mapa" in prompt
    assert "fonte" in prompt
    assert "inclinação" in prompt
