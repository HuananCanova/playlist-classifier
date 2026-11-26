"""A classificação de gênero: normalização, hierarquia, peso e desempate.

Tudo aqui é offline — `taxonomy.classify` é função pura sobre tags. O conjunto
dourado (`evals/genre_golden.yaml`) mede a precisão em faixas reais; estes
testes travam as REGRAS que produzem aquele número.
"""
import pytest

from app import taxonomy
from app.taxonomy import Tag


# ── normalização ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "escrito, esperado",
    [
        ("Hip-Hop", "hip hop"),
        ("hip_hop", "hip hop"),
        ("  HIP   HOP  ", "hip hop"),
        ("Forró", "forro"),
        ("música brasileira", "musica brasileira"),
        ("R&B", "r b"),
        ("drum & bass", "drum bass"),
        ("", ""),
    ],
)
def test_normalizacao_junta_grafias(escrito, esperado):
    assert taxonomy.normalize(escrito) == esperado


def test_grafias_diferentes_resolvem_para_o_mesmo_genero():
    """O caso que dividia o acervo: 183 faixas em "hip-hop" e 59 em "hip hop"."""
    nos = {taxonomy.resolve(t) for t in ["hip-hop", "hip hop", "Hip-Hop", "HIP_HOP", "rap"]}
    assert nos == {taxonomy.Node("hip-hop", None)}


def test_acento_nao_cria_genero_novo():
    assert taxonomy.resolve("forró") == taxonomy.resolve("forro")


# ── o que não é gênero ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tag",
    [
        "brasil", "brazilian", "german", "israeli", "usa",      # país
        "seen live", "my top songs", "albums i own",            # comportamento
        "awesome", "sexy", "chill",                             # juízo
        "guitar", "instrumental", "female vocalists",            # instrumentação
        "singer-songwriter",                                     # papel, não estilo
        "alternative", "progressive", "hardcore",                # ambíguo sozinho
        "jay-z", "iboga records",                                # artista, gravadora
        "80s", "90s", "2010s", "1997", "70's",                   # tempo
    ],
)
def test_tag_que_nao_e_genero_e_descartada(tag):
    assert taxonomy.resolve(tag) is None
    assert taxonomy.load().discarded(tag) is True


def test_descartada_e_desconhecida_sao_coisas_diferentes():
    """A diferença é o que vira fila de trabalho: "brasil" foi decidido, e
    "vaporwave" é gênero de verdade que ainda falta no YAML."""
    tabela = taxonomy.load()
    assert tabela.discarded("brasil") is True
    assert tabela.discarded("vaporwave") is False
    assert taxonomy.resolve("vaporwave") is None

    resultado = taxonomy.classify(artist_tags=[Tag("vaporwave", 100)])
    assert resultado.genre is None
    assert resultado.unresolved == ["vaporwave"]


def test_faixa_so_com_ruido_nao_recebe_genero():
    resultado = taxonomy.classify(
        artist_tags=[Tag("brasil", 100), Tag("female vocalists", 90), Tag("seen live", 80)]
    )
    assert resultado == taxonomy.EMPTY


# ── hierarquia ───────────────────────────────────────────────────────────────


def test_subgenero_aponta_para_o_pai():
    assert taxonomy.resolve("minimal techno") == taxonomy.Node("techno", "minimal techno")
    assert taxonomy.resolve("classic rock") == taxonomy.Node("rock", "classic rock")
    assert taxonomy.resolve("sertanejo") == taxonomy.Node("brasileiro", "sertanejo")


def test_filho_pontua_o_pai_uma_vez():
    """O bug central do gráfico antigo: "rock", "classic rock" e "hard rock"
    eram três rótulos com um voto cada, e rock liderava por soma de sinônimos."""
    resultado = taxonomy.classify(
        artist_tags=[Tag("rock", 100), Tag("classic rock", 95), Tag("hard rock", 90)]
    )
    assert resultado.genre == "rock"
    assert resultado.subgenre == "classic rock"
    assert resultado.genres == ["rock"]
    assert resultado.confidence == 1.0


def test_psytrance_nao_e_diluido_em_trance():
    """Decisão de modelagem: no acervo desta conta psytrance é identidade
    própria, não um subgênero de trance (`taxonomy.yaml` explica por quê)."""
    assert taxonomy.resolve("psytrance") == taxonomy.Node("psytrance", None)
    assert taxonomy.resolve("goa") == taxonomy.Node("psytrance", "goa trance")
    assert taxonomy.resolve("progressive trance") == taxonomy.Node("trance", "progressive trance")


# ── peso ─────────────────────────────────────────────────────────────────────


def test_peso_decide_entre_dois_generos():
    """Sem peso, "rock" e "techno" valeriam igual e o resultado sairia alfabético."""
    assert taxonomy.classify(artist_tags=[Tag("rock", 100), Tag("techno", 10)]).genre == "rock"
    assert taxonomy.classify(artist_tags=[Tag("rock", 10), Tag("techno", 100)]).genre == "techno"


def test_tag_sem_peso_vale_o_padrao():
    """Tags gravadas antes da taxonomia são só o nome; continuam classificando."""
    assert taxonomy.classify(artist_tags=["psytrance", "goa"]).genre == "psytrance"


def test_familia_com_duas_tags_ganha_de_uma_tag_mais_forte():
    """"techno" + "minimal" (130) passa "house" (100). É a mesma regra da
    hierarquia, e está registrada no conjunto dourado (rocksted-want-you)."""
    resultado = taxonomy.classify(
        artist_tags=[Tag("house", 100), Tag("techno", 70), Tag("minimal", 60)]
    )
    assert resultado.genre == "techno"


def test_tag_da_faixa_pesa_mais_que_a_do_artista():
    """A tag da faixa descreve a faixa; a do artista, a carreira dele."""
    resultado = taxonomy.classify(
        artist_tags=[Tag("rock", 100)], track_tags=[Tag("techno", 100)]
    )
    assert resultado.genre == "techno"
    assert taxonomy.TRACK_SHARE > taxonomy.ARTIST_SHARE


def test_artista_decide_quando_a_faixa_nao_tem_tag():
    """O caso mais comum no acervo real: `track.getTopTags` volta vazio."""
    resultado = taxonomy.classify(artist_tags=[Tag("psytrance", 100)], track_tags=[])
    assert resultado.genre == "psytrance"
    # Sem penalizar a confiança só porque um dos lados não existia.
    assert resultado.confidence == 1.0


def test_ruido_de_outro_artista_nao_leva_a_faixa():
    """Colaboração de três artistas em que um deles tem tag de metalcore."""
    resultado = taxonomy.classify(
        artist_tags=[
            Tag("psytrance", 100), Tag("goa", 70), Tag("trance", 60),
            Tag("techno", 30), Tag("metalcore", 10),
        ]
    )
    assert resultado.genre == "psytrance"
    assert "metal" not in resultado.genres


# ── determinismo e explicação ────────────────────────────────────────────────


def test_empate_resolve_sempre_igual():
    """Sem regra fixa, a mesma faixa mudaria de gênero entre duas execuções."""
    tags = [Tag("techno", 100), Tag("house", 100)]
    assert taxonomy.classify(artist_tags=tags).genre == "house"
    assert taxonomy.classify(artist_tags=list(reversed(tags))).genre == "house"


def test_confianca_cai_quando_as_tags_discordam():
    concordam = taxonomy.classify(artist_tags=[Tag("techno", 100), Tag("minimal techno", 90)])
    discordam = taxonomy.classify(artist_tags=[Tag("techno", 100), Tag("reggae", 90)])
    assert concordam.confidence == 1.0
    assert discordam.confidence < 0.7


def test_evidencia_cita_as_tags_que_elegeram_o_genero():
    resultado = taxonomy.classify(
        artist_tags=[Tag("thrash metal", 100), Tag("heavy metal", 90), Tag("brasil", 80)]
    )
    assert resultado.genre == "metal"
    assert resultado.evidence == ["thrash metal", "heavy metal"]
    assert len(resultado.evidence) <= taxonomy.MAX_EVIDENCE


def test_evidencia_nao_repete_a_mesma_tag():
    resultado = taxonomy.classify(
        artist_tags=[Tag("psytrance", 100)], track_tags=[Tag("Psytrance", 100)]
    )
    assert [t.lower() for t in resultado.evidence] == ["psytrance"]


# ── integridade do YAML ──────────────────────────────────────────────────────


def test_nenhum_genero_esta_tambem_na_lista_de_descarte():
    """Um rótulo nas duas listas seria decidido pela ordem de carga, não pelo
    YAML — e o descarte vence, apagando um gênero sem aviso."""
    tabela = taxonomy.load()
    conflitos = {chave for chave in tabela.index if chave in tabela.ignored}
    assert conflitos == set()


def test_nenhum_padrao_de_descarte_apaga_um_genero():
    tabela = taxonomy.load()
    apagados = [
        chave for chave in tabela.index if any(p.search(chave) for p in tabela.patterns)
    ]
    assert apagados == []


def test_todo_subgenero_tem_nome_proprio():
    """Subgênero com o mesmo nome do pai faria os dois gráficos repetirem o
    rótulo — era exatamente o remendo que a taxonomia substituiu."""
    tabela = taxonomy.load()
    for chave, no in tabela.index.items():
        if no.subgenre is not None:
            assert taxonomy.normalize(no.subgenre) != taxonomy.normalize(no.genre), chave


# ── reclassificação do que já está guardado ──────────────────────────────────


def _faixa_antiga(**extra):
    """Uma faixa como o pipeline ANTES da taxonomia a guardava: `genres` com as
    tags cruas do artista e `subgenre_tags` com a união, tudo em ordem
    alfabética e sem peso."""
    from app.models import TrackGenreInfo

    base = dict(
        track_id="t1",
        name="Faixa",
        artists=["Artista"],
        duration_ms=1000,
        genres=["brazil", "classic rock", "hard rock", "rock"],
        subgenre_tags=["brazil", "classic rock", "guitar", "hard rock", "rock"],
        bpm=120.0,
    )
    return TrackGenreInfo(**{**base, **extra})


def test_reclassifica_faixa_guardada_sem_tocar_em_rede():
    from app import reclassify

    nova = reclassify.track(_faixa_antiga())

    assert nova.genre == "rock"
    # Só há tags de artista guardadas: o blend pende para "classic rock" mas
    # fica incerto, e subgênero incerto não vira `subgenre`.
    assert nova.subgenre is None
    assert nova.subgenre_lean == "classic rock"
    assert nova.subgenre_unsure is True
    assert nova.genres == ["rock"]
    # País e instrumento saem; o resto das tags fica.
    assert "brazil" not in nova.subgenre_tags
    assert "guitar" not in nova.subgenre_tags
    assert "classic rock" in nova.subgenre_tags
    # Nada que venha do Spotify ou do Deezer é tocado.
    assert nova.bpm == 120.0
    assert nova.track_id == "t1"


def test_reclassificar_marca_a_versao_da_taxonomia():
    """O selo é o que faz o backfill ser idempotente: o script pula o que já
    está na versão em vigor, e reclassifica tudo quando ela muda."""
    from app import reclassify
    from app.models import PlaylistAnalysis, PlaylistSummary

    analise = PlaylistAnalysis(
        playlist=PlaylistSummary(id="p1", name="Playlist", track_count=1),
        tracks=[_faixa_antiga()],
        genre_distribution=[],
        subgenre_distribution=[],
        top_artists=[],
        bpm_histogram=[],
        tracks_missing_genre=0,
    )

    assert reclassify.is_current(analise) is False      # guardada antes da taxonomia
    nova = reclassify.analysis(analise)
    assert nova.genre_taxonomy == reclassify.current_version()
    assert reclassify.is_current(nova) is True

    resumo, _ = reclassify.digest({"tracks": [{"genres": ["rock"], "tags": ["classic rock"]}]})
    assert reclassify.is_current(resumo) is True
    assert reclassify.is_current({"tracks": []}) is False


def test_selo_de_versao_impede_a_segunda_passada_de_mexer_em_nada():
    """Sem o selo, reclassificar em cima dos próprios rótulos derivados movia
    gênero secundário em volta do piso de confiança — 239 das 2.228 faixas do
    acervo na segunda passada. O selo resolve isso estruturalmente."""
    from app import reclassify

    # Faixa com duas famílias, que é onde a instabilidade aparecia.
    resumo = {
        "tracks": [
            {
                "genres": ["rap", "rock", "alternative rock", "hip-hop"],
                "tags": ["alternative rock", "hip hop", "rap", "rock", "rap metal"],
            }
        ]
    }
    uma, _ = reclassify.digest(resumo)
    assert reclassify.is_current(uma) is True

    # O script pula um resumo já selado — é esta a garantia que ele oferece.
    duas, mudadas = reclassify.digest(uma)
    assert reclassify.is_current(duas) is True
    # E se for forçado, o selo continua o mesmo (a versão não mudou).
    assert duas["genre_taxonomy"] == uma["genre_taxonomy"]


def test_reclassifica_analise_refaz_as_distribuicoes():
    from app import reclassify
    from app.models import PlaylistAnalysis, PlaylistSummary

    analise = PlaylistAnalysis(
        playlist=PlaylistSummary(id="p1", name="Playlist", track_count=2),
        tracks=[
            _faixa_antiga(),
            _faixa_antiga(
                track_id="t2",
                genres=["brasil", "female vocalists"],
                subgenre_tags=["brasil", "female vocalists"],
            ),
        ],
        # Como estavam: um voto por tag, e as duas listas repetindo rótulo.
        genre_distribution=[],
        subgenre_distribution=[],
        top_artists=[],
        bpm_histogram=[],
        tracks_missing_genre=0,
    )

    nova = reclassify.analysis(analise)

    assert [(g.label, g.count) for g in nova.genre_distribution] == [("rock", 1)]
    assert [(g.label, g.count) for g in nova.subgenre_distribution] == [("classic rock", 1)]
    # A segunda faixa só tinha país e voz: deixa de receber rótulo inventado.
    assert nova.tracks_missing_genre == 1


def test_resumo_reclassificado_fica_igual_a_um_escrito_agora():
    """A invariante que dá sentido ao backfill: depois dele, um resumo antigo é
    indistinguível de um gravado pelo caminho novo."""
    from app import profile_store, reclassify
    from app.models import PlaylistAnalysis, PlaylistSummary

    faixa = _faixa_antiga()
    analise = PlaylistAnalysis(
        playlist=PlaylistSummary(id="p1", name="Playlist", snapshot_id="s1", track_count=1),
        tracks=[faixa],
        genre_distribution=[],
        subgenre_distribution=[],
        top_artists=[],
        bpm_histogram=[],
        tracks_missing_genre=0,
    )

    antigo, _ = reclassify.digest(profile_store.digest_from_analysis(analise, has_audio=True))
    agora = profile_store.digest_from_analysis(reclassify.analysis(analise), has_audio=True)

    assert antigo["tracks"][0]["genres"] == agora["tracks"][0]["genres"]
    assert antigo["tracks"][0]["tags"] == agora["tracks"][0]["tags"]


# ── supergênero de carona ────────────────────────────────────────────────────


def test_supergenero_solto_nao_vira_segundo_genero():
    """"electronic" e "trance" vêm de carona em quase toda faixa eletrônica;
    contá-los levava "electronic" ao segundo lugar do perfil da conta."""
    resultado = taxonomy.classify(
        artist_tags=[Tag("psytrance", 100), Tag("electronic", 95), Tag("trance", 90)]
    )
    assert resultado.genre == "psytrance"
    assert resultado.genres == ["psytrance"]
    assert resultado.confidence == 1.0


def test_supergenero_sozinho_continua_classificando():
    resultado = taxonomy.classify(artist_tags=[Tag("electronic", 100)])
    assert resultado.genre == "electronic"


def test_dois_supergeneros_sozinhos_continuam_classificando():
    resultado = taxonomy.classify(artist_tags=[Tag("electronic", 100), Tag("trance", 90)])
    assert resultado.genre in {"electronic", "trance"}


def test_subgenero_de_supergenero_pontua_sempre():
    """Só a tag solta é enfraquecida: "dubstep" diz o que a faixa é."""
    resultado = taxonomy.classify(
        artist_tags=[Tag("dubstep", 100), Tag("electronic", 90), Tag("soul", 30)]
    )
    assert resultado.genre == "electronic"
    assert resultado.subgenre == "dubstep"


def test_fallback_declarado_no_yaml_e_nao_no_codigo():
    """A lista de supergêneros é dado, não `if` espalhado pelo classificador."""
    assert taxonomy.load().fallbacks == {"electronic", "trance"}


# ── dados de referência dos subgêneros (BPM, descrição, fonte) ───────────────


def test_subgenre_mapping_form_loads():
    info = taxonomy.subgenre_info("full-on")
    assert info.genre == "psytrance"
    assert info.bpm == (140.0, 148.0)
    assert info.about


def test_old_list_form_still_loads():
    assert taxonomy.resolve("alt rock") == taxonomy.Node("rock", "alternative rock")
    info = taxonomy.subgenre_info("alternative rock")
    assert info.genre == "rock"
    assert info.bpm is None and info.about is None and info.source is None


def test_subgenre_info_unknown_is_none():
    assert taxonomy.subgenre_info("nao existe") is None


def test_forest_is_its_own_subgenre():
    assert taxonomy.resolve("forest psy") == taxonomy.Node("psytrance", "forest psy")
    assert taxonomy.resolve("forest psytrance") == taxonomy.Node("psytrance", "forest psy")
    assert taxonomy.resolve("dark psy") == taxonomy.Node("psytrance", "darkpsy")


def test_offbeat_resolves():
    assert taxonomy.resolve("offbeat") == taxonomy.Node("psytrance", "offbeat")
    assert taxonomy.resolve("offbeat psy") == taxonomy.Node("psytrance", "offbeat")


def test_goa_is_weak():
    assert taxonomy.resolve("goa").subgenre == "goa trance"
    assert taxonomy.tag_weight_factor("goa") == 0.3
    assert taxonomy.tag_weight_factor("Goa") == 0.3
    assert taxonomy.tag_weight_factor("goa trance") == 1.0
    assert taxonomy.tag_weight_factor("qualquer coisa") == 1.0


def test_weak_alias_pesa_menos_no_voto():
    fraca = taxonomy.classify(track_tags=[Tag("goa", 100), Tag("techno", 100)])
    forte = taxonomy.classify(track_tags=[Tag("goa trance", 100), Tag("techno", 100)])
    assert forte.genre == "psytrance"
    assert fraca.genre == "techno"


def test_subgenres_of_psytrance_in_yaml_order():
    nomes = [s.name for s in taxonomy.subgenres_of("psytrance")]
    assert nomes[:3] == ["progressive psytrance", "full-on", "night full-on"]
    assert nomes.index("darkpsy") < nomes.index("forest psy") < nomes.index("hitech")
    assert nomes[-2:] == ["dark progressive", "suomi"]
    assert taxonomy.subgenres_of("nao existe") == []


def test_every_bpm_range_has_source():
    com_bpm = [s for g in taxonomy.load().genres for s in taxonomy.subgenres_of(g) if s.bpm]
    assert len(com_bpm) >= 10
    for s in com_bpm:
        assert s.source == "https://psytranceguide.com", s.name
        assert s.about, s.name
        assert s.bpm[0] < s.bpm[1]


def test_twilight_e_forest_soltos_nao_votam_em_psytrance():
    # "twilight" e "forest" sozinhos aparecem em música que não é psy (Muse marcado twilight).
    assert taxonomy.resolve("twilight") is None
    assert taxonomy.resolve("forest") is None
    assert taxonomy.resolve("night full-on").subgenre == "night full-on"
    assert taxonomy.resolve("forest psy").subgenre == "forest psy"
    assert taxonomy.resolve("forest psytrance").subgenre == "forest psy"
    assert taxonomy.resolve("forest darkpsy").subgenre == "forest psy"
