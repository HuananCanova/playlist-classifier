"""Congela as entradas do conjunto dourado de subgênero.

    cd backend
    .venv/Scripts/python.exe -m evals.congelar_subgeneros             # tudo
    .venv/Scripts/python.exe -m evals.congelar_subgeneros --so-selo   # só o selo

Lê `subgenre_refs.yaml` (faixa + subgênero de referência externa), consulta o
Last.fm (tags da faixa e do artista, com peso) e o Deezer (BPM e selo do
lançamento) e escreve `subgenre_golden.yaml` com as entradas CONGELADAS: o
runner roda offline e dá sempre o mesmo número, e só este script — rodado de
propósito — muda os dados.

`--so-selo` preenche apenas o `selo` dos casos que o arquivo já tem e mantém
todo o resto (tags, BPM, `incompleto`) exatamente como estava congelado — para
medir o selo sem recongelar o Last.fm, que pode estar fora de alcance.

Seguro para repetir: **não grava no banco do app** (os caches que escrevem em
`enrichment_store` viram no-op, como em `scripts/medir_fontes_psy.py`) e,
quando uma consulta falha (Last.fm sem resposta, Deezer fora do ar), reaproveita
o que o arquivo anterior já tinha para a faixa em vez de congelar "sem dados"
como se fosse resposta. Faixa que continua sem resposta ganha `incompleto: true`.
Os `limiares` do arquivo anterior são preservados, com o comentário que os
justifica.
"""
import argparse
import asyncio
import sys
from pathlib import Path

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import deezer_client, enrichment_store, lastfm_client  # noqa: E402
from app.lastfm_client import NoAnswer  # noqa: E402

AQUI = Path(__file__).resolve().parent
REFS_PATH = AQUI / "subgenre_refs.yaml"
GOLDEN_PATH = AQUI / "subgenre_golden.yaml"
TENTATIVAS = 3
PAUSA_S = 1.5



def _isolar_do_banco() -> None:
    """Os clientes leem e guardam no banco do app; o congelamento não pode tocar
    nele (nem ler: o que já estava lá não é "o que a API devolve agora").

    Vale para todo `get_*`/`put_*` de `enrichment_store` — inclusive caches que
    apareçam depois, como o de selo por álbum. Feito ao rodar, não ao importar:
    importar o módulo (nos testes) não pode desligar o banco do resto do app.
    """
    for nome in dir(enrichment_store):
        if nome.startswith(("get_", "put_")) and callable(getattr(enrichment_store, nome)):
            setattr(enrichment_store, nome, lambda *a, **k: None)

CABECALHO = """\
# Conjunto dourado de subgênero — entradas CONGELADAS.
#
# Gerado por `python -m evals.congelar_subgeneros` a partir de `subgenre_refs.yaml`.
# NÃO edite os casos à mão: refaça o congelamento. Cada caso guarda o que o
# Last.fm (tags da faixa e do artista, com peso) e o Deezer (BPM) devolveram na
# data do congelamento, e o rótulo `subgenero` vem da referência externa
# registrada em `referencia` — nunca de julgamento nosso nem do classificador.
#
# Formato: id, faixa, referencia, subgenero, artista (tags do artista),
# faixa_tags (tags da faixa), bpm (null = Deezer sem BPM ou sem a faixa),
# selo (gravadora do lançamento no Deezer; "" = o álbum não tem selo, null =
# não capturado: faixa fora do Deezer ou consulta que falhou),
# incompleto (true = alguma fonte não respondeu no congelamento).
#
# `--so-selo` refaz só o `selo` e deixa tags e BPM como estavam congelados.
#
# `limiares` são os pisos/tetos que `run_subgenre_evals.py` cobra.

"""


def _comentario_dos_limiares(texto: str) -> str:
    """As linhas de comentário logo abaixo de `limiares:` no arquivo anterior.

    O `yaml.safe_dump` não carrega comentários, e ali fica o registro de cada
    corrida e de por que os limiares são o que são — recongelar não pode
    apagá-lo."""
    linhas = texto.splitlines(keepends=True)
    for i, linha in enumerate(linhas):
        if linha.rstrip() == "limiares:":
            comentario = []
            for seguinte in linhas[i + 1:]:
                if not seguinte.lstrip().startswith("#"):
                    break
                comentario.append(seguinte)
            return "".join(comentario)
    return ""


def _tags(lista) -> list[list]:
    return [[t.name, round(t.weight)] for t in lista]


async def _com_tentativas(fabrica):
    """Repete até a fonte responder de verdade; devolve (resultado, respondeu)."""
    resultado = None
    for i in range(TENTATIVAS):
        if i:
            await asyncio.sleep(PAUSA_S * i)
        resultado = await fabrica()
        if not isinstance(resultado, (NoAnswer, deezer_client.Incomplete)):
            return resultado, True
    return resultado, False


def _achou(info) -> bool:
    """A busca do Deezer respondeu: achou (com id) ou disse que não tem."""
    return info is not None and (info.get("deezer_id") is not None or isinstance(info, deezer_client.NotFound))


async def _selo(
    client: httpx.AsyncClient, artista: str, titulo: str, info: dict | None = None
) -> tuple[str | None, bool]:
    """(selo, respondeu). O selo só sai do detalhe do álbum, então a faixa
    precisa ser achada no Deezer antes.

    Faixa que o Deezer não tem (`NotFound`) é resposta: selo None, respondeu.
    Busca que não respondeu — dict vazio comum, sem id — ou selo None de
    `get_track_label` é falha, e quem chama reaproveita o selo anterior.

    `info` = a busca que o passo do BPM já fez; se ela respondeu, não se
    procura a faixa de novo.
    """
    for i in range(0 if _achou(info) else TENTATIVAS):
        if i:
            await asyncio.sleep(PAUSA_S * i)
        info = await deezer_client.get_track_info(client, artista, titulo)
        if _achou(info):
            break
    deezer_id = (info or {}).get("deezer_id")
    if deezer_id is None:
        return None, isinstance(info, deezer_client.NotFound)

    for i in range(TENTATIVAS):
        if i:
            await asyncio.sleep(PAUSA_S * i)
        selo = await deezer_client.get_track_label(client, deezer_id)
        if selo is not None:
            return selo, True
    return None, False


def _com_selo(antigo: dict, selo: str | None) -> dict:
    """O caso congelado com o `selo` trocado e nada mais — mesma ordem de
    campos, `selo` logo depois do `bpm`."""
    caso: dict = {}
    for chave, valor in antigo.items():
        if chave == "selo":
            continue
        caso[chave] = valor
        if chave == "bpm":
            caso["selo"] = selo
    caso.setdefault("selo", selo)
    return caso


async def so_selo_caso(client: httpx.AsyncClient, ref: dict | None, antigo: dict) -> dict:
    """Refaz só o `selo` de um caso já congelado. Falha mantém o selo anterior,
    como o congelamento completo faz com as outras fontes; sem selo anterior
    fica null e o caso ganha `incompleto` (null sozinho leria como "a faixa
    não está no Deezer"). Tags e BPM não mudam."""
    if ref is None:
        return _com_selo(antigo, antigo.get("selo"))
    selo, ok = await _selo(client, ref["artista"], ref["titulo"])
    if ok:
        return _com_selo(antigo, selo)
    caso = _com_selo(antigo, antigo.get("selo"))
    if "selo" not in antigo:
        caso["incompleto"] = True
    return caso


async def congelar_caso(client: httpx.AsyncClient, ref: dict, antigo: dict | None) -> dict:
    artista, titulo = ref["artista"], ref["titulo"]
    credito = ref.get("credito") or artista
    caso = {
        "id": ref["id"],
        "faixa": f"{credito} — {titulo}",
        "referencia": ref["referencia"],
        "subgenero": ref["subgenero"],
    }
    incompleto = False

    tags_artista, ok = await _com_tentativas(lambda: lastfm_client.get_artist_tags(client, artista))
    if not ok and antigo is not None:
        caso["artista"] = antigo.get("artista") or []
    else:
        incompleto = incompleto or not ok
        caso["artista"] = _tags(tags_artista)

    tags_faixa, ok = await _com_tentativas(lambda: lastfm_client.get_track_tags(client, artista, titulo))
    if not ok and antigo is not None:
        caso["faixa_tags"] = antigo.get("faixa_tags") or []
    else:
        incompleto = incompleto or not ok
        caso["faixa_tags"] = _tags(tags_faixa)

    info, ok = await _com_tentativas(lambda: deezer_client.get_track_info(client, artista, titulo))
    if not ok and antigo is not None:
        caso["bpm"] = antigo.get("bpm")
    else:
        incompleto = incompleto or not ok
        caso["bpm"] = (info or {}).get("bpm")

    selo, ok_selo = await _selo(client, artista, titulo, info)
    if not ok_selo and antigo is not None and "selo" in antigo:
        caso["selo"] = antigo["selo"]
    else:
        incompleto = incompleto or not ok_selo
        caso["selo"] = selo
    ok = ok and ok_selo

    if incompleto or (not ok and antigo is not None and antigo.get("incompleto")):
        caso["incompleto"] = True
    return caso


async def main_async(so_selo: bool = False) -> int:
    _isolar_do_banco()
    refs = yaml.safe_load(REFS_PATH.read_text(encoding="utf-8"))["casos"]
    antigos: dict[str, dict] = {}
    limiares = {"precisao_confiante": 0.0, "max_incerto": 1.0}
    comentario = ""
    if GOLDEN_PATH.exists():
        texto_anterior = GOLDEN_PATH.read_text(encoding="utf-8")
        comentario = _comentario_dos_limiares(texto_anterior)
        anterior = yaml.safe_load(texto_anterior) or {}
        antigos = {c["id"]: c for c in anterior.get("casos") or []}
        limiares = anterior.get("limiares") or limiares

    if so_selo and not antigos:
        print(f"--so-selo precisa de um {GOLDEN_PATH.name} já congelado.")
        return 1

    refs_por_id = {r["id"]: r for r in refs}
    casos = []
    async with httpx.AsyncClient() as client:
        if so_selo:
            # Os casos do arquivo, na ordem do arquivo: nada entra nem sai.
            pendentes = [(refs_por_id.get(i), antigo) for i, antigo in antigos.items()]
        else:
            pendentes = [(ref, antigos.get(ref["id"])) for ref in refs]
        for ref, antigo in pendentes:
            if so_selo:
                if ref is None:
                    print(f"{antigo['id']}: fora de {REFS_PATH.name}; selo mantido")
                caso = await so_selo_caso(client, ref, antigo)
            else:
                caso = await congelar_caso(client, ref, antigo)
            casos.append(caso)
            print(
                f"{caso['id']:45} artista={len(caso['artista']):2d} faixa={len(caso['faixa_tags']):2d} "
                f"bpm={caso['bpm']} selo={caso.get('selo')!r}{'  INCOMPLETO' if caso.get('incompleto') else ''}"
            )

    corpo = yaml.safe_dump({"limiares": limiares, "casos": casos}, allow_unicode=True, sort_keys=False, width=110)
    corpo = corpo.replace("limiares:\n", "limiares:\n" + comentario, 1)
    GOLDEN_PATH.write_text(CABECALHO + corpo, encoding="utf-8")
    print(
        f"\n{len(casos)} casos: tags do artista {sum(1 for c in casos if c['artista'])}, "
        f"tags da faixa {sum(1 for c in casos if c['faixa_tags'])}, "
        f"BPM {sum(1 for c in casos if c['bpm'])}, "
        f"selo {sum(1 for c in casos if c.get('selo'))} (sem selo {sum(1 for c in casos if c.get('selo') == '')}, "
        f"não capturado {sum(1 for c in casos if c.get('selo') is None)}), "
        f"incompletos {sum(1 for c in casos if c.get('incompleto'))}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Congela as entradas do conjunto dourado de subgênero.")
    parser.add_argument(
        "--so-selo", action="store_true", help="preenche só o selo (Deezer); tags e BPM ficam como estão"
    )
    args = parser.parse_args()
    return asyncio.run(main_async(so_selo=args.so_selo))


if __name__ == "__main__":
    raise SystemExit(main())
