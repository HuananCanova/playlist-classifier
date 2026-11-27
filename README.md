# Playlist Classifier

Conecta com a sua conta do Spotify, lista suas playlists e gera gráficos de
gênero, subgênero e andamento — por playlist, por música e da conta inteira.

- **Spotify Web API**: autenticação OAuth, suas playlists e as faixas de cada uma.
- **Last.fm API**: as tags da comunidade, que são a fonte de gênero do projeto —
  tags do **artista** dão o gênero amplo (`techno`, `mpb`); tags da **faixa** e do
  artista alimentam o subgênero (`minimal techno`, `bossa nova`) como evidência,
  junto com o andamento (veja [Subgêneros](#subgêneros)).
- **Deezer API**: BPM e prévia de 30s de cada faixa (o Spotify cortou os dois). O
  BPM também é evidência de subgênero, comparado com as faixas de referência.
- **Claude ou Groq**: um chat que responde perguntas sobre uma playlist ou uma
  faixa consultando os dados reais por meio de ferramentas (opcional).

O que dá para fazer no app:

- **Playlist**: fluxo de gêneros ao longo da ordem das faixas, distribuição de
  gêneros e subgêneros, andamento (BPM), artistas frequentes, grupos de clima e
  a tabela de faixas com prévia.
- **Faixa**: onda sonora e espectro ao vivo, métricas do áudio medidas no
  navegador, tags, faixas parecidas e **por que** ela tem aquele subgênero.
- **Subgênero**: uma página por subgênero com a descrição, a faixa de BPM e as
  faixas do acervo que são ou "puxam para" ele.
- **Busca**: busca semântica ("melancholic guitar") sobre tudo que já foi analisado.
- **Perfil**: o retrato da conta inteira, montado sem chamar o Spotify ao abrir.
- **MCP**: as mesmas ferramentas do chat, para Claude Desktop/Code.

## Stack técnica

| Camada | Tecnologia | Uso neste projeto |
| --- | --- | --- |
| Backend | Python 3.10+ (CI e Docker usam 3.12), FastAPI, httpx | API assíncrona, chamadas concorrentes ao Spotify/Last.fm/Deezer |
| Sessão | Starlette `SessionMiddleware` | Cookie assinado e `httpOnly`; o JavaScript da página não lê os tokens do Spotify |
| Validação | Pydantic v2 + pydantic-settings | Schemas de request/response e variáveis de ambiente tipadas |
| Persistência | SQLite (biblioteca padrão, migrações versionadas) + `cachetools` (TTLCache) | Análises por versão da playlist, tags do Last.fm, BPM do Deezer e listagens sobrevivem a reinícios; memória na frente para a mesma requisição |
| Agente de IA | Anthropic Claude (`claude-opus-5`, tool use, streaming SSE) | Chat com escopo de playlist/faixa, sem dados soltos no prompt |
| Agente de IA (alternativo) | Groq (`openai/gpt-oss-120b`, API compatível com OpenAI) | Testar o agente sem custo, mesmo contrato de ferramentas |
| Protocolo de agente | [MCP](https://modelcontextprotocol.io) | As mesmas ferramentas do chat, expostas a Claude Desktop/Code |
| Classificação | Taxonomia própria em YAML + voto ponderado (`app/taxonomy.py`) e blend de evidências (`app/subgenre.py`) | Transforma tag livre de ouvinte em gênero canônico; o subgênero vira uma mistura por faixa, explicada e com "incerto" — sem rede e sem modelo |
| Busca semântica | ChromaDB (embarcado) + `all-MiniLM-L6-v2` via ONNX | Índice vetorial local, sem chave de API nem rate limit |
| Agrupamento | scikit-learn (TF-IDF + k-means) | Separa faixas de uma playlist em "climas", `k` pela silhueta |
| APIs externas | Spotify Web API (OAuth 2.0 + PKCE), Last.fm API, Deezer API | Playlists/faixas, tags de gênero, BPM e prévia de áudio |
| Frontend | React 18, Vite, React Router, react-markdown | SPA; respostas do chat renderizadas em Markdown |
| Gráficos | SVG e canvas feitos à mão (`charts/chartKit.js`) | Sem biblioteca de gráficos: fluxo de gêneros, BPM, grupos, colunas e barras |
| Áudio no navegador | Web Audio API (`AnalyserNode`) + FFT próprio | Forma de onda e espectro ao vivo; métricas de volume e bandas da prévia |
| Testes | pytest, pytest-asyncio | Suíte sem rede (fixtures) + conjunto dourado contra o modelo real |
| Infra | Docker, docker-compose, nginx | `docker compose up --build` sobe backend + frontend servido por nginx |
| CI | GitHub Actions | A cada push: testes do backend, build do frontend e build das imagens Docker; evals sob demanda |

## Arquitetura

```
playlist-classifier/
├── backend/                   FastAPI (Python)
│   ├── app/
│   │   ├── main.py            # app + middlewares (sessão, CORS) + /api/health
│   │   ├── config.py          # variáveis de ambiente
│   │   ├── models.py          # schemas Pydantic
│   │   ├── cache.py           # caches em memória (TTL)
│   │   │
│   │   ├── auth.py            # rotas /api/auth — OAuth Authorization Code + PKCE
│   │   ├── playlists.py       # rotas /api/playlists — listagem, análise, grupos
│   │   ├── tracks.py          # rotas /api/tracks — detalhe e faixas parecidas
│   │   ├── search.py          # rotas /api/search — busca semântica e varredura
│   │   ├── profile.py         # rotas /api/profile — perfil da conta
│   │   ├── chat.py            # rotas /api/chat — chat (SSE) e métricas
│   │   │
│   │   ├── spotify_client.py  # toda chamada ao Spotify passa aqui (limites e bloqueio)
│   │   ├── spotify_auth.py    # token a partir do refresh token (MCP e scripts)
│   │   ├── lastfm_client.py   # tags de artista e de faixa (a fonte de gênero)
│   │   ├── deezer_client.py   # BPM e prévia de 30s
│   │   │
│   │   ├── taxonomy.py       # tag do Last.fm -> gênero canônico (+ confiança)
│   │   ├── taxonomy.yaml     # o vocabulário: gêneros, subgêneros e descartes
│   │   ├── subgenre.py        # blend de subgêneros por evidência (tags, andamento) — puro
│   │   ├── genre_analysis.py  # combina as fontes e agrega distribuições
│   │   ├── evidence_store.py  # tags separadas e BPM por faixa, sem validade
│   │   ├── enrichment_job.py  # "Buscar evidência": Last.fm + Deezer, retomável
│   │   ├── reclassify.py      # reclassifica o que está em disco, offline
│   │   ├── subgenres.py       # rotas /api/subgenres — acervo por subgênero e o job
│   │   ├── subgenre_library.py # contagens e faixas por subgênero (funções puras)
│   │   ├── clustering.py      # grupos de clima (TF-IDF + k-means)
│   │   ├── vector_store.py    # índice vetorial (ChromaDB)
│   │   ├── indexer.py         # a varredura da conta, com ritmo e teto
│   │   ├── profile_store.py   # resumos por playlist em disco
│   │   ├── profile_stats.py   # agregações do perfil (funções puras)
│   │   │
│   │   ├── ai_tools.py        # as ferramentas do agente (neutras de provedor)
│   │   ├── ai_chat.py         # adaptador Claude + streaming SSE
│   │   ├── ai_chat_groq.py    # adaptador Groq (testes sem custo)
│   │   ├── metrics.py         # tokens e latência por turno
│   │   └── mcp_server.py      # servidor MCP (stdio)
│   ├── tests/                 # suíte sem rede
│   ├── evals/                 # conjuntos dourados (gênero, subgênero, chat)
│   └── scripts/               # SPOTIFY_REFRESH_TOKEN, reclassificar, medir fontes do psy
├── frontend/                  React + Vite
│   └── src/
│       ├── App.jsx            # rotas e navegação
│       ├── api.js             # cliente HTTP (deduplica GETs simultâneos)
│       ├── AuthContext.jsx    # usuário logado
│       ├── PlayerContext.jsx  # o único <audio> do app + analisador Web Audio
│       ├── audioAnalysis.js   # picos e métricas espectrais da prévia
│       ├── pages/             # Login, PlaylistList, PlaylistDetail, TrackDetail, Subgenre, Search, Profile
│       ├── components/        # gráficos, tabela de faixas, player, chat
│       └── charts/            # chartKit (paleta, hooks, curvas), tooltip, fluxo de gêneros
├── docs/CODEBASE_MAP.md       # mapa detalhado do código
├── docker-compose.yml
└── .github/workflows/ci.yml
```

| Rota do app | Página |
| --- | --- |
| `/login` | Entrada com Spotify |
| `/playlists` | Suas playlists |
| `/playlists/:id` | Análise de uma playlist + chat |
| `/faixa/:id` | Detalhe de uma faixa + chat |
| `/subgenero/:name` | Um subgênero: referência e faixas do acervo |
| `/busca` | Busca semântica e varredura |
| `/perfil` | Perfil da conta |

**Por que essa stack:** backend em Python/FastAPI porque é onde fica a lógica de
combinar duas fontes de dados, agregar e cachear — fácil de evoluir. Frontend em
React porque os gráficos são interativos e há navegação entre telas
(login → lista → detalhe).

**Segurança:** os tokens do Spotify nunca chegam ao navegador — ficam num cookie
de sessão assinado (`SessionMiddleware`); só o backend fala com a API do Spotify.
O login usa PKCE.

## Classificação de gênero

As tags do Last.fm são texto livre de ouvinte, e contá-las produz um gráfico de
strings, não uma classificação. No acervo de teste (2.228 faixas, 734 tags
distintas) o sintoma era claro: `hip-hop` com 183 faixas e `hip hop` com 59 eram
dois gêneros; `psy trance`, `psychedelic trance` e `psytrance` eram três; `rock`
liderava por ser contado junto com `classic rock` e `hard rock`; e `brasil`,
`german`, `female vocalists` e até `jay-z` chegavam ao gráfico como se fossem
gênero.

O classificador (`app/taxonomy.py` + `app/taxonomy.yaml`) resolve em três etapas:

1. **Normalizar** — acento, caixa e pontuação saem antes de comparar, então
   "Hip-Hop", "hip hop" e "hip_hop" são a mesma tag sem precisar listar as três.
2. **Resolver** — cada tag vira um nó de dois níveis (gênero → subgênero) ou
   nada. `minimal techno` resolve para (techno, minimal techno); `brasil` não
   resolve, porque está na lista de descarte, agrupada por motivo (geografia,
   comportamento de quem escuta, instrumentação, juízo de valor, ambíguo demais).
   Um subgênero pode ser só uma lista de aliases ou um mapeamento com dados de
   referência: `aliases`, `weak` (aliases que valem só 30% do voto), `bpm` (faixa
   mínimo–máximo), `about` (uma linha nossa) e `source` (de onde veio o BPM). No
   psytrance, `goa` sozinho é alias **fraco** de `goa trance`: no Last.fm a tag é
   um balaio e dizia mais do que sabia (`goa trance` por extenso vale o peso
   inteiro).
3. **Pontuar** — cada faixa distribui **um** voto entre os gêneros que as suas
   tags resolveram, proporcional ao `count` que o Last.fm dá a cada tag — um peso
   de 0 a 100 que o app antes descartava, fazendo `rock` com 100 e `chillwave`
   com 2 valerem igual. O subgênero pontua o gênero pai, a tag da faixa pesa mais
   que a do artista, e o empate resolve por regra fixa para o resultado não
   mudar entre execuções.

Uma quarta regra saiu da medição, não do projeto: **supergênero de carona não
conta**. `electronic` e `trance` aparecem como tag solta em quase toda faixa de
techno, house ou psytrance, e contá-los levava `electronic` ao segundo lugar do
perfil da conta sem dizer nada sobre a música. Gênero marcado `fallback` no YAML
só vale, como tag solta, quando nada mais classificou a faixa — mas os
subgêneros dele (`dubstep`, `ambient`, `progressive trance`) pontuam sempre,
porque esses dizem o que a faixa é.

Cada faixa sai com `genre`, `genre_confidence` e `genre_evidence` — as tags que
elegeram o gênero, para a interface poder explicar a decisão em vez de só
afirmá-la. O **subgênero** tem modelo próprio, descrito em
[Subgêneros](#subgêneros): o gênero sai do voto de tags (acima) e o subgênero é
decidido depois, dentro dele, por um blend de evidências.

O efeito no acervo de teste, medido depois de aplicar:

| | Antes (contando tags) | Depois (classificando) |
| --- | --- | --- |
| Rótulos distintos de gênero | 547 | **22** |
| Gráfico da playlist | um voto por tag de cada artista: uma faixa com três artistas deixava até nove | **um voto por faixa**, no gênero classificado |
| Topo do perfil da conta | rock 422, psytrance 352, electronic 338, progressive trance 208 | rock 809, psytrance 390, metal 285, pop 249 |
| Diversidade de gênero | sem significado (contava grafias) | **13,0** gêneros efetivos |

No perfil da conta, uma faixa conta em cada gênero que tenha ficado acima do
piso de confiança — "quanto do meu acervo é rock" não é pergunta exclusiva. Já o
gráfico de uma playlist conta um voto por faixa, no gênero vencedor. São
semânticas diferentes de propósito, e as duas saem da mesma classificação.

Das 2.069 faixas únicas do acervo, 2.003 recebem gênero. As 66 que sobram só
tinham tag de país, de humor ou de voz — e deixaram de receber um rótulo
inventado, com a interface dizendo isso.

### Reclassificar o que já está guardado

A taxonomia classifica no momento da análise, então playlists analisadas antes
dela ficam guardadas com os rótulos antigos — e a página de Perfil lê exatamente
esses resumos. Refazer as análises custaria uma varredura completa do Spotify, e
esta conta já foi suspensa por 18 horas uma vez por volume de requisição
(ver [Limites do Spotify](#limites-do-spotify)).

Não é preciso: as tags já estão dentro de cada análise e de cada resumo.

```bash
cd backend
python -m scripts.reclassificar_generos --dry-run   # mostra o que mudaria
python -m scripts.reclassificar_generos             # grava

# no Docker, onde fica o banco que o app serve:
docker compose exec backend python -m scripts.reclassificar_generos
docker compose restart backend                       # solta o cache em memória
```

**Não chama Spotify, Last.fm, Deezer nem modelo nenhum** — roda com a internet
desligada. Só toca gênero: BPM, prévia, data de adição e popularidade ficam como
estão. E é idempotente por construção, não por coincidência: cada análise e cada
resumo guardam em `genre_taxonomy` a versão da taxonomia que os classificou, e o
script pula o que já está em dia. Isso importa porque o dado guardado contém os
rótulos que o próprio script derivou — reclassificar em cima deles move gênero
secundário em volta do piso de confiança (medido: 239 das 2.228 faixas na
segunda passada). Com o selo, a segunda passada não reescreve nada, e subir a
versão da taxonomia reescreve tudo.

Uma diferença honesta em relação a uma análise nova: o que está guardado tem o
nome da tag, não o peso — o peso só passou a ser gravado agora. Então o backfill
decide pela taxonomia (hierarquia, sinônimo, descarte), não pela força relativa
da tag. Quando a playlist for analisada de novo, a classificação é refinada pelo
peso sem nada a desfazer.

**Como isso é medido.** `evals/genre_golden.yaml` tem 45 casos — faixas reais do
acervo com o gênero rotulado à mão, mais alguns sintéticos para as regras do
classificador — e as tags com peso imitando a distribuição da API, porque medir
sem peso mediria outro programa.

O arquivo registra também o que ficou de fora e por quê, que é a parte que
sustenta o número. Faixas com duas respostas defensáveis (Manu Chao entre latin
e reggae, Anitta entre pop e funk carioca) não entram: um conjunto dourado com
cara ou coroa dentro mede sorte. E uma delas saiu depois de entrar — "Stay High
(Habits Remix)" trocou de resposta quando a regra de supergênero chegou, o que a
revelou ambígua; rotular de novo para acompanhar a implementação seria ajustar a
régua ao que está sendo medido. Dois rótulos foram revistos (com o motivo no
arquivo) porque o julgamento inicial era o mais fraco, não para fazer o teste
passar.

```bash
cd backend
python -m evals.run_genre_evals              # precisão; falha abaixo do limiar
python -m evals.run_genre_evals --cobertura   # o que falta na taxonomia
```

```
gênero    : 45/45 = 1.000   (limiar 0.90)
subgênero : 29/29 = 1.000   (limiar 0.75)
confiança : média 0.89, mínima 0.50, máxima 1.00
```

O subgênero deste conjunto cobre só o que fica fora do psytrance (resolver tag →
subgênero na taxonomia). Os casos de subgênero do psytrance saíram daqui: pelas
regras novas muitos deles deveriam virar "incerto", e quem os mede é o conjunto
de [Subgêneros](#subgêneros).

O conjunto é pequeno e o limiar (0,90) existe para o CI reprovar regressão, não
para comemorar o 1,0 — com 45 casos, um acerto a mais ou a menos move 2 pontos.
O relatório de cobertura é o número mais honesto sobre o que falta: dos 16.610
usos de tag do acervo, **80,6%** são classificados, **15,7%** descartados de
propósito e **3,7%** ainda não têm casa no YAML — e a tag pendente mais frequente
aparece em 4 faixas. Ele sai ordenado por impacto justamente para dizer onde
vale gastar os próximos cinco minutos.

Nada disso chama rede: é função pura sobre tags, roda em CI em menos de um
segundo e não gasta uma requisição do Spotify.

## Subgêneros

O projeto nasceu para descobrir de que subgêneros uma playlist ou faixa é feita,
principalmente em música eletrônica e, dentro dela, psytrance. "Psytrance" sozinho
diz pouco: o que interessa é se é progressive, full-on, offbeat, darkpsy, forest.
E quem usa o app está **aprendendo** — o próprio ouvido não serve de gabarito, e o
app não deve decretar um rótulo como fato. Por isso o subgênero é:

- uma **mistura por faixa** (`subgenre_blend`: fatias que somam 1 entre os
  subgêneros do gênero vencedor), com o rótulo que lidera (`subgenre_lean`);
- **explicado**: cada fonte de evidência diz o que apontou e por quê;
- **"incerto"** quando a evidência é fina ou as fontes discordam, em vez de chute.
  Uma faixa incerta mantém o blend e o `subgenre_lean`, mas o `subgenre`
  afirmado fica vazio — e as telas mostram essa parte mais clara.

Sem aprendizado de máquina: é uma função pura (`app/subgenre.py`) sobre tags e
BPM, testável em CI e refeita offline sobre o que está guardado.

### Fontes de evidência

Cada fonte devolve uma distribuição sobre os subgêneros do gênero da faixa, ou
se abstém (fonte sem dado não puxa o blend para o meio). Elas são somadas,
ponderadas:

| Fonte | Entrada | Peso | O que diz |
| --- | --- | --- | --- |
| Tags da faixa | Last.fm, com o peso de cada tag | 1,0 | voto das tags que resolvem para um subgênero |
| Andamento | BPM do Deezer | 0,8 | 1 dentro da faixa de referência do subgênero, decaindo linearmente até 0 a 6 BPM de distância; onde as faixas se sobrepõem, o voto se divide |
| Selo | detalhe do álbum no Deezer + `app/labels.yaml` | 0,7 | as fatias que o mapa dá ao selo (veja [O selo](#o-selo)) |
| Tags do artista | Last.fm | 0,4 | o mesmo voto, mas pesa menos: é o artista, não a faixa |

A faixa de BPM de cada subgênero psy vem do [Guia de Psytrance](https://psytranceguide.com)
(18 estilos, v1.2, de 2017 — uma opinião curada, registrada por subgênero em
`source` no `taxonomy.yaml` para poder trocar ou somar outra referência; as
descrições são nossas, a fonte só é citada e linkada). Três detalhes do
andamento: **empate entre dois subgêneros conta como concordância** (um BPM
costuma cair onde duas faixas se sobrepõem); um BPM que cabe em **três ou mais**
subgêneros ao mesmo tempo (146 BPM cabe em seis) **não estreita nada** — entra
no blend, mas não confirma nem contraria outra fonte; e um BPM que não cabe em
nenhuma faixa é **relido como o dobro** (72 por 144, o erro de meio-tempo comum
em detectores de BPM).

Os pesos ficam em `SOURCE_WEIGHTS`, no topo de `app/subgenre.py`. Uma fonte nova
(o áudio, no Estágio B) entra como mais uma dessas distribuições, sem mexer no
resto.

### O selo

No psytrance o selo do lançamento é uma pista forte: um disco da Suntrip é goa,
um da Iboga é progressive. O selo vem do **detalhe do álbum no Deezer** (uma
chamada por álbum, sem chave, guardada por álbum em `deezer_album_labels`) e
vira subgênero pelo mapa escrito à mão em `app/labels.yaml`, tirado das listas
"Notable labels" de cada estilo no [Guia de Psytrance](https://psytranceguide.com)
— a mesma referência das faixas de BPM. Selo fora do mapa **se abstém**, e o
selo, como o artista, descreve algo maior que a faixa: sozinho ele dá direção,
nunca uma faixa afirmada (`SOURCES_THAT_NEED_COMPANY`). A página da faixa mostra
o selo com a nota e o link da fonte, e o chat recebe o mesmo para explicar.

O selo é de um lançamento, então só vale de uma correspondência **confiável**
no Deezer: a faixa de lá precisa bater título, artista e duração com a do
Spotify (a regra `alta` da página da faixa), senão pode ser outra gravação, de
outro disco. O job confere isso no detalhe da faixa, que pede de qualquer jeito
para achar o álbum. Cada selo guardado lembra de que `deezer_id` veio
(`label_deezer_id`): se a correspondência da faixa mudar, ele é perguntado de novo.

Para **pôr um selo no mapa**, siga o formato descrito no topo do
`labels.yaml`: precisa de uma **fonte citável** (sem fonte, fica na lista de
lacunas de lá); as fatias somam 1 e selo misto divide, não escolhe. **Nunca**
ajuste o mapa olhando o conjunto dourado — ele só mede. Medir:

```bash
cd backend
python -m scripts.medir_selos_psy --golden           # o mapa no conjunto dourado
python -m scripts.medir_selos_psy --faixas 400       # cobertura no acervo
python -m evals.congelar_subgeneros --so-selo        # recongela só o selo dos casos
```

Os números e as lacunas estão na
[spec](docs/superpowers/specs/2026-11-25-subgenre-evidence-design.md#record-label-evidence-added-2026-11-26-replaces-stage-b-for-now).

### O que é "incerto"

A faixa fica incerta (`subgenre_unsure`) quando acontece qualquer um destes:

- **só o artista ou o selo falaram** — tags de artista e selo, juntos ou
  separados, nunca decidem, nem com um andamento que cabe em três ou mais
  subgêneros ao lado;
- **o vencedor tem pouca fatia** — abaixo de `UNSURE_MIN_SHARE` (0,4);
- **as duas fontes mais pesadas discordam** — os rótulos de topo não se tocam.

Por isso **a maioria das faixas de psytrance começa incerta**: o Last.fm quase
não tem tags por faixa de psy (só do artista) e o Deezer tem BPM para poucas
(veja os limites abaixo). Sem tag de faixa nem andamento, só resta o artista — e
o artista sozinho não afirma nada. É o comportamento pretendido: um "full-on"
errado mostrado como fato é pior do que "incerto".

### Buscar evidência (o job de enriquecimento)

As análises guardadas antes não têm o que o modelo precisa: as tags estavam
misturadas (faixa e artista, sem peso) e a varredura da conta pulava o Deezer. O
botão **"Buscar evidência"** (no Perfil e na página do subgênero) resolve isso:

- busca, por faixa do acervo, as tags do Last.fm **separadas** (artista e faixa,
  com peso), o BPM do Deezer e o **selo** (um pedido por álbum, guardado), e
  grava em `track_evidence` (sem validade, para reclassificar offline depois);
- **não chama o Spotify**: as faixas vêm dos resumos já guardados — a regra do
  projeto depois da suspensão de 18 horas;
- só roda por pedido, mostra quantas faixas faltam, roda em segundo plano com
  progresso, pode ser interrompido e é **retomável**: refazer depois de uma falha
  busca só o que falta. Falha de rede não vira dado (fica sem valor e conta como
  erro); "o Deezer respondeu que não tem" é registrado à parte;
- começa pelas faixas de psytrance, onde há faixa de BPM e a evidência muda a
  resposta;
- ao terminar, **reclassifica o que está em disco**, offline (`app/reclassify.py`).
  O mesmo vale rodando `python -m scripts.reclassificar_generos`.

Análises feitas depois da mudança já gravam as tags separadas e com peso, então
não precisam do job para isso. O selo é diferente: a análise de playlist só usa
o selo já guardado (sem rede); quem busca é o job e a página da faixa.

### As telas

- **Playlist**: o gráfico de subgêneros soma as fatias do blend de cada faixa;
  na barra, a parte sólida vem de faixas afirmadas e a clara de incertas, então
  "quanto disso é palpite" fica visível. Clicar num subgênero filtra a tabela
  (as que ele lidera, afirmadas primeiro, depois as que "puxam para" ele). Numa
  playlist de um gênero só, o caminho ao longo da ordem das faixas aparece no
  nível de subgênero, quando há ao menos dois.
- **Faixa**: "Por que este subgênero" mostra o blend, uma linha por fonte de
  evidência e a referência ("full-on: 140–148 BPM, segundo psytranceguide.com"),
  e o selo com a nota e a fonte quando ele está no mapa. Quando está incerta, diz
  o que falta.
- **`/subgenero/:name`**: a descrição, a faixa de BPM e o link da fonte, e as
  faixas do acervo em dois grupos — "classificadas como X" e "puxam para X" —,
  cada um ordenado pela fatia, com prévia e as playlists onde aparece. Ouvir o
  segundo grupo faz parte de aprender. A lista de subgêneros do acervo fica no
  Perfil.

### Como isso é medido

```bash
cd backend
python -m evals.run_subgenre_evals            # resumo e tabela por subgênero
python -m evals.run_subgenre_evals --verboso  # com a evidência de cada faixa
```

O conjunto (`evals/subgenre_golden.yaml`) não usa o ouvido de quem mantém o app:
cada rótulo vem de **fora** — os exemplos que o Guia de Psytrance lista para cada
estilo e o gênero/subgênero que a **página da faixa no Beatport** exibe (olhada
à mão, com a URL registrada por caso em `evals/subgenre_refs.yaml`). Faixa que o
Beatport marca só como "Psy-Trance", ou de forma ambígua, ficou de fora em vez de
completar a cota por palpite. As entradas (tags do Last.fm, BPM do Deezer) são
**congeladas** por `evals/congelar_subgeneros.py`, então o runner roda offline e
dá sempre o mesmo número.

Os números de hoje, sem enfeite:

```
35 casos
precisão confiante : 0/0 = indefinida   (piso 0.65)
taxa de incerto    : 35/35 = 1.000   (teto 1.00)
top-2              : 17/35 = 0.486
```

A leitura honesta: hoje o app **não afirma nenhum** dos 35 casos. "Incerto"
nunca conta como acerto. Numa primeira medição ele afirmava 7 (5 certos, 2
errados), mas os 7 eram "tag do artista + um BPM que cabe em três ou mais
subgêneros" — o andamento não estreitava nada e o artista decidia sozinho, que
é justamente o que o app promete não fazer. Sem tag de faixa no conjunto, sobra
o top-2 (17 de 35) como sinal de que o blend aponta na direção certa. O selo
votou em 9 casos e concordou com a referência em 7 (top-2 subiu de 16 para 17),
mas não afirma nada sozinho, por desenho. O piso de
precisão (0,65, da primeira medição) só se aplica quando houver caso confiante —
o primeiro errado reprova; o teto de incerto fica em 1,0 porque não há folga
acima de 35/35. Existem para reprovar regressão, não para comemorar.

### Limites medidos

- **BPM do Deezer para psytrance: ~8%.** Na amostra de 150 faixas psy do acervo
  (354 distintas), o Deezer achou 80, mas só **12 têm BPM** (8%); numa primeira
  amostra de 50 foram 8 (16%). A cobertura de ~43% medida em música comercial não
  vale para psy. O andamento fica no desenho (é barato), mas a maioria do psy
  seguirá incerta até haver outra fonte de andamento.
- **O Last.fm não devolveu tag de faixa nenhuma** para as faixas de referência.
  Resultado: a fonte mais pesada (tags da faixa) **não foi testada** no conjunto
  dourado — e o BPM sozinho quase sempre cabe em vários subgêneros, então nenhum
  caso sai afirmado.
- **`UNSURE_MIN_SHARE = 0.4` e os pesos das fontes são provisórios.** O limiar
  foi escolhido com aqueles 7 casos confiantes da primeira medição, que já não
  saem confiantes — hoje nenhum caso o testa. Os pesos (`SOURCE_WEIGHTS`) são
  valores iniciais, escolhidos à mão, nunca ajustados no conjunto. O comentário
  no código marca isso. Refazer a medição quando houver tags de faixa reais ou
  andamento medido no áudio.
- **O Discogs foi avaliado e descartado.** Os estilos de lançamento que ele devolve
  para o psy do acervo são só `Psy-Trance`, `Progressive Trance` e `Goa Trance` —
  nada mais fino (o darkpsy do Klipsun volta como Psy-Trance / Progressive
  Trance). Não separam subgêneros, então a fonte de lançamento não foi construída;
  o cliente e o token ficam, sem uso, caso uma referência futura precise. A
  medição está em `scripts/medir_fontes_psy.py`.
- A faixa de BPM de cada subgênero é uma única referência, de 2017, e as faixas se
  sobrepõem (progressive e offbeat, por exemplo).

**Próximo passo — Estágio B:** medir o **andamento no áudio**, a partir das
prévias de 30s do Deezer (as mesmas que o player já toca), para preencher os ~92%
do psy sem BPM, e depois comparar o áudio com faixas de referência como mais uma
fonte de evidência. O BPM detectado no navegador foi tentado e removido (60% de
acerto); o modelo de áudio teria de superar isso no conjunto dourado.

## O chat com IA

Um agente Claude (`claude-opus-5`) que responde sobre as playlists do usuário.
O ponto central do desenho: **o agente não recebe os dados prontos no prompt** —
ele os busca através de ferramentas.

```
pergunta do usuário
      ↓
  agente ──chama──> ferramentas presas a UMA playlist ou faixa
      ↓               └─> análise em cache, grupos, índice vetorial
  resposta em streaming (SSE)
```

O chat abre num botão flutuante em dois lugares: a página da playlist e a página
da faixa. Cada conversa fica presa ao que está na tela:

| Escopo | Ferramenta | O que faz |
| --- | --- | --- |
| Playlist | `analisar_esta_playlist` | gêneros, subgêneros, artistas frequentes, amostra de faixas |
| Playlist | `buscar_nesta_playlist` | busca semântica recortada pelos ids da própria playlist |
| Playlist | `grupos_desta_playlist` | os grupos de clima, para o modelo dar nome a cada um |
| Faixa | `analisar_esta_faixa` | tags do Last.fm, tags do artista, BPM e prévia do Deezer |
| Faixa | `faixas_parecidas` | vizinhas no índice vetorial — dentro do que já foi analisado no app, e o modelo é instruído a dizer isso |

Por que assim:

- **Escopo pela forma, não pelo prompt**: a requisição traz `playlist_id` *ou*
  `track_id`, e as ferramentas são closures presas a esse id — nenhuma aceita id
  como parâmetro. O modelo não tem como pedir outra playlist, mesmo que queira.
  Isso é testado em `tests/test_scope.py`.
- **Extensibilidade**: uma ferramenta nova é um registro a mais em `build_tools()`.
- **Sem alucinação de dados**: o modelo não tem como inventar uma faixa que não
  existe, porque os nomes e números vêm da ferramenta.
- **Custo controlado**: cada ferramenta tem teto de tamanho (15 gêneros, 10
  artistas, amostra de 40 faixas, 12 resultados de busca), e o resultado avisa ao
  modelo quando é uma amostra — em vez de despejar a playlist inteira.
- **Uma varredura por turno, não por ferramenta**: analisar e depois buscar na
  mesma playlist reaproveita a análise em cache, sem refazer Spotify + Last.fm.
- **Modelos menores que repetem chamadas**: no Groq, uma chamada idêntica à
  anterior recebe o resultado já calculado com um aviso para responder, e ao
  atingir o limite de iterações o agente fecha a resposta com o que tem.
- **Credencial fora do alcance do modelo**: o token do Spotify fica capturado no
  closure das ferramentas, não como parâmetro delas.
- **Troca de provedor**: as ferramentas vivem em `ai_tools.py`, neutras. Os
  adaptadores só traduzem para cada API — o Claude (alvo real) e o Groq (que é
  compatível com OpenAI, não com a Anthropic, e serve para testar sem custo).
  Ambos emitem os mesmos eventos SSE, então o frontend não sabe qual respondeu.

O chat é opcional: sem a chave do provedor configurado em `CHAT_PROVIDER`, o
`/api/chat/status` responde `available: false` e a interface esconde o botão,
com o resto do app intacto.

## Servidor MCP

As mesmas ferramentas do chat também rodam como um servidor
[MCP](https://modelcontextprotocol.io), então qualquer cliente MCP — Claude
Desktop, Claude Code — consegue consultar suas playlists direto.

O escopo aqui é maior de propósito. No chat de dentro do app o agente responde
dentro de uma tela e fica preso a uma playlist ou faixa por conversa; via MCP o
cliente é você, dono da conta, então existe `listar_playlists` e as outras
ferramentas recebem o id como parâmetro:

| Ferramenta | Argumentos | O que devolve |
| --- | --- | --- |
| `listar_playlists` | — | id, nome e nº de faixas de todas as playlists |
| `analisar_playlist` | `playlist_id` | gêneros, subgêneros, artistas frequentes, amostra de faixas |
| `analisar_faixa` | `track_id` | tags do Last.fm, tags do artista, BPM e prévia do Deezer |

A formatação das respostas é literalmente a mesma do chat (`analisar_playlist_json`
e `analisar_faixa_json`, em `app/ai_tools.py`) — o servidor MCP é só mais uma
tradução daquele registro de ferramentas, ao lado dos adaptadores da Anthropic e
da OpenAI.

### Configurar

O servidor roda fora do navegador, sem cookie de sessão, então precisa de um
refresh token próprio. **Pare o backend** (o script usa a mesma porta do
`SPOTIFY_REDIRECT_URI`) e rode uma vez:

```bash
cd backend
python -m scripts.spotify_refresh_token
```

Ele abre o navegador, você autoriza, e o terminal imprime a linha para colar no
`backend/.env`:

```
SPOTIFY_REFRESH_TOKEN=AQD...
```

Depois, registre o servidor no cliente MCP. No Claude Code:

```bash
claude mcp add playlist-classifier -- /caminho/para/backend/.venv/bin/python -m app.mcp_server
```

Em clientes que leem um JSON de configuração, o equivalente é `command` apontando
para o Python do venv, `args` com `["-m", "app.mcp_server"]` e `cwd` na pasta
`backend`.

## Busca semântica

A análise de gênero conta tags exatas: ela sabe que 14 faixas têm a tag
`shoegaze`. O que ela não consegue é responder *"quais faixas são melancólicas
com guitarra"* — nenhuma faixa carrega esse texto literal.

Para isso cada faixa vira um documento (nome, artistas, álbum e tags) embutido
em um vetor; a pergunta vira um vetor no mesmo espaço, e a resposta é a
proximidade entre eles. Na prática, "melancholic guitar" acha faixas marcadas
como *sad*, *wistful* ou *dream pop* sem que a palavra apareça em lugar nenhum.

Isso aparece em três lugares:

- **`/busca`** — busca livre sobre tudo que você já analisou.
- **Página da faixa** — a seção *Parecidas com esta*, por vizinhança de vetores.
- **Chat** — `buscar_nesta_playlist` no escopo de playlist e `faixas_parecidas`
  no escopo de faixa. A primeira é recortada pelos ids da própria playlist, então
  a busca não vaza faixas de fora do escopo da conversa.

### Como o índice é montado

Por dois caminhos, que se complementam:

1. **Ao analisar uma playlist.** Os dados já foram buscados, então indexar não
   custa nenhuma chamada externa a mais.
2. **Por varredura da conta**, quando você pede. A tela de busca e o perfil
   mostram quantas playlists faltam e quantas chamadas ao Spotify indexá-las
   custaria, e oferecem um botão. É a mesma varredura nos dois lugares, e ela
   alimenta o índice e os resumos do perfil de uma vez (veja
   [Limites do Spotify](#limites-do-spotify)).

Reindexação usa o `snapshot_id` do Spotify, que muda quando o conteúdo da
playlist muda: playlists intactas são puladas, editadas voltam para a fila.

`AUTO_INDEX=true` no `backend/.env` volta a disparar a varredura ao abrir o app.
O padrão é `false`.

### Decisões

| Decisão | Por quê |
| --- | --- |
| Chroma embarcado, não pgvector | O app é local-first e sem banco. Subir um Postgres ao lado contradiria isso; o Chroma persiste em `backend/.chroma` e não pede processo nenhum. |
| Embeddings locais (all-MiniLM-L6-v2, ONNX) | Rodam na CPU, sem chave de API e sem rate limit. Baixa ~80 MB uma vez. |
| Distância cosseno, não L2 | Documentos de tags variam muito de tamanho (2 tags numa faixa obscura, 40 numa popular) e a euclidiana leria comprimento como diferença de conteúdo. |
| Um documento por faixa | A mesma música em três playlists deve aparecer uma vez na busca global. O recorte por playlist vem de um filtro por id. |

**Limitação conhecida:** o modelo de embeddings é treinado em inglês, e as tags
do Last.fm também são. Consultas em inglês funcionam bem; em português a
separação entre resultados fica mais fraca. Trocar por um modelo multilíngue é
uma mudança de uma linha em `_build_collection()`.

## Grupos de clima

A distribuição de gêneros diz do que a playlist é feita — 34% indie rock, 21%
dream pop. O que ela não mostra é que essas fatias podem ser blocos separados:
uma playlist de 60 faixas costuma ser duas ou três playlists convivendo, e a
contagem global achata isso numa média que não descreve nenhuma delas.

As faixas viram vetores TF-IDF das suas tags, o k-means separa os blocos, e o
`k` é escolhido pela maior silhueta entre 2 e 6. O painel na página da playlist
mostra os grupos e uma projeção 2D deles; no chat, `grupos_desta_playlist`
devolve os mesmos dados para o modelo dar nome a cada grupo em português.

O rótulo de cada grupo vem das tags que mais o **distinguem** do resto da
playlist, não das mais frequentes nele. A diferença importa: numa playlist com
um bloco de shoegaze e um de metal, `guitar` é a tag mais comum dos dois e não
serve para nomear nenhum.

**O que não entra nas features:** BPM seria o sinal numérico mais interessante,
mas só existe via Deezer, uma chamada por faixa — caro demais para um painel que
carrega junto com a página. As features espectrais do `audioAnalysis.js` são
calculadas no navegador, só para a faixa tocando. Sobra o que a análise já tem:
tags, duração e popularidade, com as duas últimas pesando pouco (0,35) para não
dominarem as tags.

## Perfil

A aba **Perfil** é um **retrato do gosto**, não um relatório do acervo: o que
essa pessoa ouve. Um retrato em uma frase abre a página, e abaixo dele vêm as
facetas que o sustentam — gênero dominante, variedade, época, fidelidade a
artistas, onde o gosto cai entre o hit e o garimpo, em que andamento —, os
gêneros e artistas mais presentes, como o gosto mudou ano a ano, os garimpos
mais fora do radar e uma tabela comparando as playlists lado a lado. Só entram
playlists que o Spotify deixa ler (suas e colaborativas).

O que **não** entra é tão deliberado quanto o que entra: faixas explícitas,
faixas repetidas entre playlists, duração média e afins são fatos da
biblioteca, e ocupariam o lugar de algo que diz alguma coisa sobre a pessoa. O
critério para qualquer número novo é o mesmo: ele responde "o que essa pessoa
ouve?" ou não entra.

Abrir o perfil não chama o Spotify. O painel sai do que já existe:

1. **Resumos no banco** (SQLite em `backend/.data/`): toda análise feita no app —
   abrir uma playlist ou a varredura da conta — grava um resumo compacto da
   playlist. Ele vale enquanto o `snapshot_id` do Spotify não muda e sobrevive a
   reinícios. Os resumos da versão anterior, em `backend/.profile_cache/`, são
   importados sozinhos.
2. **O índice da busca**: enquanto faltam resumos, artistas e estilos de todas
   as faixas já indexadas aparecem num painel à parte, sem chamada nenhuma.
3. **O botão "Analisar as que faltam"** dispara a varredura da conta, com a
   estimativa de chamadas e de tempo antes de começar. Ela pula o Deezer (BPM e
   prévia), que sozinho levaria minutos numa conta inteira; o BPM médio usa as
   faixas que já têm BPM.

Enquanto a varredura roda, a página acompanha o progresso e recarrega o painel a
cada playlist concluída.

Análises simultâneas da mesma playlist (página + varredura) viram uma só.

## Limites do Spotify

Em setembro de 2026 o Spotify suspendeu o app por ~18 horas (`Retry-After:
65527`). Nenhuma chamada isolada foi o problema: ler as 113 playlists da conta
custa ~250 chamadas. O volume veio de repetições — duas varreduras separadas
(busca e perfil) relendo a conta inteira, a varredura automática a cada visita,
um `/me` por página aberta, e reinícios do backend que esqueciam o bloqueio e
voltavam a chamar uma API bloqueada. O Spotify não publica os limites de apps em
modo de desenvolvimento, então o código trata o volume como recurso escasso:

| Proteção | Onde |
| --- | --- |
| Toda chamada ao Spotify passa pelo `SpotifyClient` — inclusive `/me` e o detalhe de faixa | `spotify_client.py` |
| Espera acima de 60s vira **bloqueio do app inteiro**, gravado em `backend/.state/` e respeitado depois de reinícios; nada sai para o Spotify até ele acabar | `spotify_client.py` |
| Esperas curtas valem por rota sem o id (`/v1/playlists/{id}/items`), para outra playlist não parecer um endpoint livre | `spotify_client.py` |
| Perfil do usuário guardado na sessão no login; renovado a cada 12h. Um bloqueio não desloga mais | `auth.py` |
| Listagem de playlists em memória **e em disco**: sem nova chamada depois de um reinício, e a última lista conhecida serve as páginas durante um bloqueio | `playlists.py` |
| **Uma** varredura, só por botão: uma playlist por vez, 2s de pausa, no máximo 60 por hora, repete a mesma playlist numa espera curta e para no primeiro bloqueio longo | `indexer.py` |
| A tela mostra quanto uma varredura vai custar antes de começar, e quanto falta de um bloqueio | busca e perfil |

`GET /api/health` mostra o estado atual (`spotify_throttled.global_block_seconds`).

## Testes, evals e observabilidade

```bash
cd backend
python -m pytest                      # suíte rápida, sem rede
python -m evals.run_evals             # conjunto dourado, contra o modelo real
python -m evals.run_evals --provider groq --verbose
```

**A suíte (`backend/tests`)** não toca em Spotify, Last.fm, Deezer nem em modelo
nenhum: tudo que sai para a rede vira fixture. O que ela cobre de mais
importante é o escopo do chat — a promessa de que uma conversa fala de uma
playlist *ou* de uma faixa não é feita pelo prompt (que o modelo pode ignorar) e
sim pela forma das ferramentas, que não aceitam id. Isso é testável, e é testado.

**O conjunto dourado (`backend/evals`)** roda o agente de verdade contra o
provedor configurado, mas ainda com a camada de dados trocada por fixtures — o
custo de rodar é só o do modelo, nunca o da API do Spotify. Cada caso declara as
ferramentas que a resposta deveria ter usado, e todos passam por uma checagem
automática de alucinação: qualquer faixa citada que não exista na fixture reprova
o caso.

**Métricas** ficam em `GET /api/chat/metrics`: tokens, tempo até o primeiro
texto, tempo total e ferramentas por turno, agregados por provedor. É o que
transforma "o Groq parece mais rápido" em um número — e o runner de evals imprime
o mesmo resumo no fim de cada execução.

## Docker

```bash
docker compose up --build
```

Sobe backend (`127.0.0.1:8000`) e frontend servido por nginx
(`127.0.0.1:5173`). O índice vetorial, os resumos do perfil e o estado do
Spotify (bloqueio e listagem) ficam em três volumes nomeados, então recriar os
containers não zera nada. O modelo de embeddings é baixado durante o build da
imagem, não no primeiro uso.

O endereço da API (`VITE_API_URL`) entra no bundle do frontend no build: para
apontar para outro backend, é preciso reconstruir a imagem.

Útil por si só, e ainda contorna um problema real de desenvolvimento aqui: o
projeto mora numa pasta do OneDrive, onde o observador de arquivos do uvicorn
perde alterações e passa a servir código velho.

## A migração da API do Spotify (2026)

Vale registrar, porque explica várias decisões do código. As mudanças de
[fevereiro](https://developer.spotify.com/documentation/web-api/references/changes/february-2026)
e março de 2026 quebraram algumas suposições do projeto:

| Mudança | Efeito | Como o código lida |
|---|---|---|
| `GET /playlists/{id}/tracks` removido | 403 em toda análise | Usa `/playlists/{id}/items`; cada entrada agora é `item`, não `track` |
| Endpoints em lote removidos (`GET /artists?ids=`, `/tracks`, `/albums`…) | 403 ao buscar artistas | Busca individual por artista, com concorrência limitada + cache |
| Campo `genres` removido do objeto de artista | Spotify deixou de fornecer gênero | Gênero passou a vir das tags de artista do Last.fm |
| Contagem migrou de `tracks.total` para `items.total` | Toda playlist aparecia com 0 músicas | Lê `items.total` com fallback pro campo deprecado |
| `/playlists/{id}/items` só responde para playlists do usuário ou colaborativas | 403 ao abrir playlists apenas seguidas | A listagem filtra por dono (`/me`) ou `collaborative`; um 403 vira mensagem, não logout |

A terceira é a mais estrutural: o Spotify não fornece mais dado de gênero
nenhum, então o Last.fm deixou de ser complemento e virou a única fonte.

## Passo a passo para rodar localmente

### 1. Criar um app no Spotify

1. Acesse https://developer.spotify.com/dashboard e crie um app.
2. Em **Settings**, adicione esta Redirect URI exatamente assim:
   `http://127.0.0.1:8000/api/auth/callback`
3. Copie o **Client ID** e o **Client Secret**.

### 2. Criar uma API key do Last.fm

1. Acesse https://www.last.fm/api/account/create e crie uma "aplicação".
2. Copie a **API key** (não precisa da secret, só fazemos leitura pública).

### 3. (Opcional) Chave de IA, para o chat

Sem chave nenhuma o app funciona normalmente, só sem a aba de chat.

```bash
# Claude (padrão)
CHAT_PROVIDER=anthropic
ANTHROPIC_API_KEY=...   # https://console.anthropic.com/settings/keys

# ou Groq, que tem camada gratuita — útil para testar
CHAT_PROVIDER=groq
GROQ_API_KEY=...        # https://console.groq.com/keys
```

### 4. Configurar o backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edite .env e preencha SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, LASTFM_API_KEY
# gere um SESSION_SECRET com: openssl rand -hex 32

uvicorn app.main:app --port 8000
```

### 5. Configurar o frontend

Em outro terminal:

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

### 6. Usar

Abra **`http://127.0.0.1:5173`** e clique em **Entrar com Spotify**.

> ⚠️ Use `127.0.0.1`, não `localhost`. O backend aceita só essa origem (CORS) e o
> cookie de sessão é `SameSite=Lax` — pro navegador, `localhost` e `127.0.0.1` são
> domínios diferentes, então o login silenciosamente não completa.

## Notas de implementação

- **Concorrência do Last.fm**: é uma requisição por faixa e por artista, então a
  concorrência define o tempo total. Medido contra a API real com 60 buscas:
  8 → 1,69s · 16 → 1,22s · 24 → 1,08s · 32 → 0,74s, sem nenhum 429. O projeto usa
  24, e uma busca que falhe degrada para "sem tags" em vez de derrubar a análise.
- **Persistência**: o trabalho caro fica num SQLite (`backend/.data/`, ou
  `DATA_DIR`). A análise completa de uma playlist vale enquanto o `snapshot_id`
  não muda, então reabrir uma playlist não chama ninguém (medido: ~6,6s na
  primeira vez, ~15ms depois, inclusive após reiniciar o backend). Tags do
  Last.fm, correspondências do Deezer e metadados de faixa valem 30 dias, por
  faixa, então playlists que dividem artistas pagam uma vez só. Uma playlist
  varrida sem áudio é completada só com o Deezer ao ser aberta. Falhas de rede
  nunca ficam guardadas como resposta. A prévia do Deezer é uma URL assinada que
  expira, então não é guardada: a faixa guarda o id, e o player pede a URL atual
  na hora do play.
- **Permissão**: a análise guardada é por playlist, não por pessoa. Ela só é
  servida a uma conta cuja listagem (vinda do Spotify) contém a playlist; fora
  disso a análise é relida no Spotify, que responde 403 se a conta não puder ver.
- **Cache em memória**: fica na frente do banco, por processo. A listagem de
  playlists vale 5 minutos; o bloqueio do Spotify fica em `backend/.state/` (veja
  [Limites do Spotify](#limites-do-spotify)).
- **Dados faltando**: faixas locais e indisponíveis vêm com campos `null` (não
  ausentes), então o código usa `.get(x) or default` em vez de `.get(x, default)`.
- **Gráficos**: todos desenhados à mão em SVG ou canvas, sem biblioteca. A paleta
  categórica (`SERIES` em `charts/chartKit.js`) tem seis cores validadas para
  contraste e para distinção entre daltônicos sobre o fundo escuro; categorias
  além delas viram "outros". Barras de distribuição usam uma cor só, exceto quando
  acompanham as cores do fluxo de gêneros. Nos grupos de clima, cada grupo tem cor
  **e** forma, porque cor sozinha não garante separação entre todos os pares.
- **BPM no navegador foi testado e removido**: um detector por autocorrelação
  acertou 60% das vezes em que respondeu (erros de oitava e tercina) contra os
  dados do Deezer. O BPM exibido vem só do Deezer.
- **React StrictMode** dispara efeitos duas vezes em desenvolvimento. O `api.js`
  junta GETs idênticos em andamento numa só requisição, para isso não virar o
  dobro de chamadas ao backend (e, por tabela, ao Spotify).

## Limitações conhecidas / próximos passos

- **Uso pessoal / single-user**: a sessão fica num cookie, não há banco de
  usuários. Para publicar, seria preciso um session store real (Redis/DB) e
  revisar CORS/cookies para produção.
- **Cobertura de gênero**: artistas independentes ou pouco conhecidos podem não
  ter tags no Last.fm — isso aparece no contador de "músicas sem gênero
  identificado".
- **Subgênero do psytrance**: a maior parte das faixas fica "incerta" até haver
  BPM e tags de faixa — veja os [limites medidos](#limites-medidos).
- **Chat**: o histórico vive no estado do React; recarregar a página ou mudar de
  playlist/faixa zera a conversa. Não há persistência entre sessões.
- **Métricas do chat**: ficam em memória e zeram quando o backend reinicia.
- **Busca em português**: veja a limitação do modelo de embeddings em
  [Busca semântica](#busca-semântica).
- **Faixas parecidas** só encontram faixas já indexadas — não é recomendação sobre
  o catálogo inteiro.
- **Frontend sem testes nem lint**: a garantia hoje é o `npm run build` no CI.
- **Ideias de evolução**: andamento medido no áudio (Estágio B, veja
  [Subgêneros](#subgêneros)); classificação por IA para as faixas que o Last.fm não
  cobre; um modelo de embeddings multilíngue; exportar a análise.

## Testando rapidamente

```bash
# backend
cd backend && python -m pytest                 # suíte sem rede
cd backend && python -m evals.run_genre_evals  # precisão da classificação de gênero
cd backend && python -m evals.run_subgenre_evals  # subgênero contra referências externas

# frontend
cd frontend && npm run build                   # garante que o build de produção funciona
```

Para o mapa detalhado do código — módulos, rotas, fluxos e armadilhas — veja
[docs/CODEBASE_MAP.md](docs/CODEBASE_MAP.md).

## Contribuidores

- [@HuananCanova](https://github.com/HuananCanova)
- [@k9va90](https://github.com/k9va90)
