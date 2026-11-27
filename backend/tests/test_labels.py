"""O selo do lançamento como evidência de subgênero.

Sem rede e sem banco: o nome do selo chega pronto, e o mapa é um YAML.
"""
import pytest

from app import labels, subgenre
from app.taxonomy import Tag


# ── normalização do nome ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "escrito",
    ["Spin Twist Records", "spin twist records", "SPIN TWIST RECORDS", "Spin-Twist  Records"],
)
def test_grafias_do_mesmo_selo_resolvem_igual(escrito):
    """O Deezer escreve o mesmo selo de várias formas."""
    assert labels.lookup(escrito).name == "Spin Twist Records"


def test_alias_resolve_para_o_selo():
    assert labels.lookup("Spintwist Records").name == "Spin Twist Records"
    assert labels.lookup("Twisted Records Ltd").name == "Twisted Records"


def test_nome_parecido_nao_vira_o_mesmo_selo():
    """Tirar "records" do nome juntaria selos distintos — por isso não tiramos."""
    assert labels.lookup("Twisted Records").name == "Twisted Records"
    assert labels.lookup("Twisted") is None


# ── abstenção ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "selo",
    [
        "Universal Music Australia Pty. Ltd.",
        "Pink Floyd Records",
        "Spinnin' Records",
        "Kontor Records",
        "Lord Huron",  # nome de artista no campo de selo
        "Shamanic Tales",  # lacuna conhecida: sem estilo equivalente aqui
        "Blue Tunes Records",  # idem ("Tribal" não é modelado)
    ],
)
def test_selo_fora_do_mapa_se_abstem(selo):
    """Entre as faixas psy da biblioteca aparecem majors e até nome de artista
    no campo de selo. Nenhum pode votar."""
    assert labels.lookup(selo) is None
    assert labels.label_source("psytrance", selo) is None


def test_sem_selo_se_abstem():
    assert labels.label_source("psytrance", None) is None
    assert labels.label_source("psytrance", "") is None


def test_selo_de_psy_nao_fala_de_faixa_de_rock():
    """As fatias do selo são subgêneros de psytrance; num rock, ele se cala."""
    assert labels.label_source("rock", "Suntrip Records") is None


# ── o voto ───────────────────────────────────────────────────────────────────


def test_selo_de_um_estilo_so_aponta_aquele_subgenero():
    fonte = labels.label_source("psytrance", "Parvati Records")
    assert fonte.name == "label"
    assert fonte.distribution == {"forest psy": 1.0}
    assert fonte.evidence[0].says == "forest psy"
    assert "Parvati" in fonte.evidence[0].detail


def test_selo_misto_reparte_em_vez_de_escolher():
    fonte = labels.label_source("psytrance", "Iboga Records")
    assert set(fonte.distribution) == {"progressive psytrance", "hypnotic psy"}
    assert fonte.distribution["progressive psytrance"] > fonte.distribution["hypnotic psy"]
    assert sum(fonte.distribution.values()) == pytest.approx(1.0)
    # Repartido, o selo não aponta um rótulo só; o detalhe lista as fatias.
    assert fonte.evidence[0].says is None
    assert "reparte" in fonte.evidence[0].detail


def test_fatias_somam_um():
    for nome in ["Horrordelic Records", "Stereo Society", "Suntrip Records"]:
        fonte = labels.label_source("psytrance", nome)
        assert sum(fonte.distribution.values()) == pytest.approx(1.0), nome


def test_evidencia_explica_em_palavras_nossas():
    """O detalhe vai para a tela: precisa dizer algo, não só o rótulo."""
    detalhe = labels.label_source("psytrance", "Suntrip Records").evidence[0].detail
    assert "Suntrip" in detalhe and "goa" in detalhe
    assert len(detalhe) > 20


# ── no blend ─────────────────────────────────────────────────────────────────


def test_selo_sozinho_nao_deixa_a_faixa_confiante():
    """Um selo de full-on lança uma faixa mais lenta sem deixar de ser aquele
    selo: sozinho ele aponta uma direção, não a faixa."""
    r = subgenre.blend(
        "psytrance",
        artist_tags=[],
        track_tags=[],
        extra=[labels.label_source("psytrance", "Parvati Records")],
    )
    assert r.lean == "forest psy"
    assert r.unsure is True
    assert r.subgenre is None


def test_selo_com_artista_concordando_ainda_precisa_de_mais():
    """Selo e artista descrevem os dois algo maior que a faixa."""
    r = subgenre.blend(
        "psytrance",
        artist_tags=[Tag("forest psy", 100)],
        track_tags=[],
        extra=[labels.label_source("psytrance", "Parvati Records")],
    )
    assert r.lean == "forest psy"
    assert r.unsure is True


def test_selo_confirma_a_tag_da_faixa():
    r = subgenre.blend(
        "psytrance",
        artist_tags=[],
        track_tags=[Tag("forest psy", 100)],
        extra=[labels.label_source("psytrance", "Parvati Records")],
    )
    assert r.subgenre == "forest psy"
    assert r.unsure is False


def test_selo_discordando_da_tag_da_faixa_deixa_incerto():
    r = subgenre.blend(
        "psytrance",
        artist_tags=[],
        track_tags=[Tag("psychill", 100)],
        extra=[labels.label_source("psytrance", "Parvati Records")],
    )
    assert r.unsure is True


def test_selo_entra_na_evidencia_da_faixa():
    r = subgenre.blend(
        "psytrance",
        artist_tags=[],
        track_tags=[Tag("forest psy", 100)],
        extra=[labels.label_source("psytrance", "Parvati Records")],
    )
    assert any(e.source == "label" for e in r.evidence)


# ── integridade do YAML ──────────────────────────────────────────────────────


def _selos():
    """Cada selo uma vez (o índice tem uma entrada por grafia)."""
    return {info.name: info for info in labels.load().by_name.values()}.values()


def test_todo_subgenero_do_mapa_existe_na_taxonomia():
    """Um rótulo com erro de digitação viraria um selo que nunca vota."""
    from app import taxonomy

    validos = {i.name for i in taxonomy.subgenres_of("psytrance")}
    for info in _selos():
        for sub in info.shares:
            assert sub in validos, f"{info.name}: {sub!r} não é subgênero de psytrance"


def test_todo_selo_tem_fonte_e_nota():
    """Sem fonte não dá para conferir; sem nota a tela não tem o que mostrar."""
    for info in _selos():
        assert info.fonte.startswith("http"), info.name
        assert info.nota, info.name
        assert info.estilos, info.name


# ── blend_with_label: o atalho que todo caminho de classificação usa ─────────


def test_blend_with_label_inclui_o_voto_do_selo():
    r = labels.blend_with_label(
        "psytrance", artist_tags=[], track_tags=[Tag("forest psy", 100)], bpm=None, label="Parvati Records"
    )
    assert r.subgenre == "forest psy"
    assert any(e.source == "label" for e in r.evidence)


@pytest.mark.parametrize("selo", [None, "", "Kontor Records"])
def test_blend_with_label_sem_selo_util_e_o_blend_puro(selo):
    sem = subgenre.blend("psytrance", artist_tags=[Tag("full-on", 100)], track_tags=[], bpm=146.0)
    com = labels.blend_with_label(
        "psytrance", artist_tags=[Tag("full-on", 100)], track_tags=[], bpm=146.0, label=selo
    )
    assert com == sem
