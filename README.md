# Playlist Classifier

Conecta com a sua conta do Spotify, lista suas playlists e gera gráficos de
gênero, subgênero e andamento — por playlist, por música e da conta inteira.

- **Spotify Web API**: autenticação OAuth, suas playlists e as faixas de cada uma.
- **Last.fm API**: as tags da comunidade, que são a fonte de gênero do projeto —
  tags do **artista** dão o gênero amplo (`techno`, `mpb`), tags da **faixa** dão o
  subgênero (`minimal techno`, `bossa nova`), com granularidade por música.
- **Deezer API**: BPM e prévia de 30s de cada faixa (o Spotify cortou os dois).
- **Claude ou Groq**: um chat que responde perguntas sobre uma playlist ou uma
  faixa consultando os dados reais por meio de ferramentas (opcional).

O que dá para fazer no app:

- **Playlist**: fluxo de gêneros ao longo da ordem das faixas, distribuição de
  gêneros e subgêneros, andamento (BPM), artistas frequentes, grupos de clima e
  a tabela de faixas com prévia.
- **Faixa**: onda sonora e espectro ao vivo, métricas do áudio medidas no
  navegador, tags e faixas parecidas.
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
│   │   ├── genre_analysis.py  # combina as fontes e agrega distribuições
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
│   ├── evals/                 # conjunto dourado contra o modelo real
│   └── scripts/               # gerar o SPOTIFY_REFRESH_TOKEN
├── frontend/                  React + Vite
│   └── src/
│       ├── App.jsx            # rotas e navegação
│       ├── api.js             # cliente HTTP (deduplica GETs simultâneos)
│       ├── AuthContext.jsx    # usuário logado
│       ├── PlayerContext.jsx  # o único <audio> do app + analisador Web Audio
│       ├── audioAnalysis.js   # picos e métricas espectrais da prévia
│       ├── pages/             # Login, PlaylistList, PlaylistDetail, TrackDetail, Search, Profile
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
| `/busca` | Busca semântica e varredura |
| `/perfil` | Perfil da conta |

**Por que essa stack:** backend em Python/FastAPI porque é onde fica a lógica de
combinar duas fontes de dados, agregar e cachear — fácil de evoluir. Frontend em
React porque os gráficos são interativos e há navegação entre telas
(login → lista → detalhe).

**Segurança:** os tokens do Spotify nunca chegam ao navegador — ficam num cookie
de sessão assinado (`SessionMiddleware`); só o backend fala com a API do Spotify.
O login usa PKCE.

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
- **Chat**: o histórico vive no estado do React; recarregar a página ou mudar de
  playlist/faixa zera a conversa. Não há persistência entre sessões.
- **Métricas do chat**: ficam em memória e zeram quando o backend reinicia.
- **Busca em português**: veja a limitação do modelo de embeddings em
  [Busca semântica](#busca-semântica).
- **Faixas parecidas** só encontram faixas já indexadas — não é recomendação sobre
  o catálogo inteiro.
- **Frontend sem testes nem lint**: a garantia hoje é o `npm run build` no CI.
- **Ideias de evolução**: classificação por IA para as faixas que o Last.fm não
  cobre; um modelo de embeddings multilíngue; exportar a análise.

## Testando rapidamente

```bash
# backend
cd backend && python -m pytest                 # suíte sem rede

# frontend
cd frontend && npm run build                   # garante que o build de produção funciona
```

Para o mapa detalhado do código — módulos, rotas, fluxos e armadilhas — veja
[docs/CODEBASE_MAP.md](docs/CODEBASE_MAP.md).

## Contribuidores

- [@HuananCanova](https://github.com/HuananCanova)
- [@k9va90](https://github.com/k9va90)
