# Playlist Classifier

Conecta com a sua conta do Spotify, lista suas playlists e gera gráficos de
gênero e subgênero — por playlist e por música.

- **Spotify Web API**: autenticação OAuth, suas playlists e as faixas de cada uma.
- **Last.fm API**: as tags da comunidade, que são a fonte de gênero do projeto —
  tags do **artista** dão o gênero amplo (`techno`, `mpb`), tags da **faixa** dão o
  subgênero (`minimal techno`, `bossa nova`), com granularidade por música.
- **Claude API**: um chat que responde perguntas sobre as suas playlists
  consultando os dados reais por meio de ferramentas (opcional).

## Stack técnica

| Camada | Tecnologia | Uso neste projeto |
| --- | --- | --- |
| Backend | Python 3.11+, FastAPI, httpx | API assíncrona, chamadas concorrentes ao Spotify/Last.fm/Deezer |
| Sessão | Starlette `SessionMiddleware` | Cookie assinado; tokens do Spotify nunca chegam ao navegador |
| Validação | Pydantic v2 + pydantic-settings | Schemas de request/response e variáveis de ambiente tipadas |
| Cache | `cachetools` (TTLCache) | Evita estourar o rate limit do Spotify/Last.fm |
| Agente de IA | Anthropic Claude (tool use, streaming SSE) | Chat com escopo de playlist/faixa, sem dados soltos no prompt |
| Agente de IA (alternativo) | Groq (`llama-3.3-70b`, API compatível com OpenAI) | Testar o agente sem custo, mesmo contrato de ferramentas |
| Protocolo de agente | [MCP](https://modelcontextprotocol.io) | As mesmas ferramentas do chat, expostas a Claude Desktop/Code |
| Busca semântica | ChromaDB (embarcado) + `all-MiniLM-L6-v2` via ONNX | Índice vetorial local, sem chave de API nem rate limit |
| Agrupamento | scikit-learn (TF-IDF + k-means) | Separa faixas de uma playlist em "climas", `k` pela silhueta |
| APIs externas | Spotify Web API (OAuth 2.0 + PKCE), Last.fm API, Deezer API | Playlists/faixas, tags de gênero, BPM e prévia de áudio |
| Frontend | React 18, Vite, React Router, Recharts | SPA, gráficos de distribuição de gênero/BPM |
| Áudio no navegador | Web Audio API (`AnalyserNode`) | Forma de onda e espectro da prévia tocando, ao vivo |
| Testes | pytest, pytest-asyncio | Suíte sem rede (fixtures) + conjunto dourado contra o modelo real |
| Infra | Docker, docker-compose, nginx | `docker compose up --build` sobe backend + frontend servido por nginx |
| CI | GitHub Actions | Roda a suíte de testes e o build do frontend a cada push |

## Arquitetura

```
playlist-classifier/
├── backend/          FastAPI (Python) — OAuth com Spotify, chamadas às APIs, análise de gênero
│   └── app/
│       ├── main.py            # app + middlewares (sessão, CORS)
│       ├── config.py          # variáveis de ambiente
│       ├── auth.py            # OAuth Authorization Code + PKCE, refresh de token
│       ├── spotify_client.py  # chamadas à Spotify Web API
│       ├── lastfm_client.py   # tags de artista e de faixa (a fonte de gênero)
│       ├── genre_analysis.py  # combina as duas fontes e agrega distribuições
│       ├── playlists.py       # rotas /api/playlists
│       ├── artists.py         # /api/artists/{id} — Spotify + Last.fm + acervo
│       ├── ai_tools.py        # as ferramentas do agente (neutras de provedor)
│       ├── ai_chat.py         # adaptador Claude + streaming SSE
│       ├── ai_chat_groq.py    # adaptador Groq (testes sem custo)
│       ├── chat.py            # rotas /api/chat
│       ├── models.py          # schemas Pydantic
│       └── cache.py           # cache em memória (TTL) pra não estourar rate limit
└── frontend/         React + Vite — login, lista de playlists, gráficos (Recharts)
    └── src/
        ├── App.jsx / AuthContext.jsx
        ├── pages/    Login, PlaylistList, PlaylistDetail, TrackDetail, ArtistDetail
        ├── charts/   GenreFlow (fita + atos + faixas por gênero)
        └── components/  gráficos de barras, tabela de faixas, lista de artistas
```

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
  agente ──chama──> visao_geral(limite)     ──> N playlists EM PARALELO
      ↓             listar_playlists()      ──> Spotify
      ↓             analisar_playlist(id)   ──> Spotify + Last.fm
  resposta em streaming (SSE)
```

Existe em dois lugares: a aba **Chat**, que enxerga a conta toda, e um painel na
página da playlist, restrito a ela. O escopo é aplicado no servidor — com
`playlist_id` na requisição, o agente recebe só a ferramenta daquela playlist e
não tem como alcançar as outras.

Por que assim:

- **Extensibilidade**: adicionar busca ou recomendação é registrar uma ferramenta
  nova em `build_tools()`. Nada mais no arquivo muda.
- **Sem alucinação de dados**: o modelo não tem como inventar uma playlist que
  não existe, porque os nomes e números vêm da ferramenta.
- **Custo controlado**: cada ferramenta tem teto de tamanho. Uma playlist de 300
  faixas devolve ~1.300 tokens (15 gêneros, 10 artistas, amostra de 40 faixas), e
  o resultado avisa ao modelo que é uma amostra — em vez de despejar as 300.
- **O fan-out caro mora na ferramenta, não no laço do modelo.** Perguntas amplas
  levavam o modelo a analisar uma playlist por turno: 59s e nenhuma resposta,
  porque estourava o limite de chamadas. A `visao_geral` analisa várias em
  paralelo numa chamada só — o mesmo cenário caiu para 3,9s. Vale registrar que
  o `gpt-oss-120b` ignora a instrução de agrupar chamadas num mesmo turno, então
  a solução não podia depender da colaboração do modelo.
- **Amostragem honesta**: a visão geral pega as *maiores* playlists (mais faixas,
  mais sinal) em vez das primeiras da lista, e devolve a cobertura real em faixas
  e porcentagem, que o modelo é instruído a declarar na resposta.
- **Credencial fora do alcance do modelo**: o token do Spotify fica capturado no
  closure das ferramentas, não como parâmetro delas.
- **Troca de provedor**: as ferramentas vivem em `ai_tools.py`, neutras. Os
  adaptadores só traduzem para cada API — o Claude (alvo real) e o Groq (que é
  compatível com OpenAI, não com a Anthropic, e serve para testar sem custo).
  Ambos emitem os mesmos eventos SSE, então o frontend não sabe qual respondeu.

O chat é opcional: sem `ANTHROPIC_API_KEY`, o `/api/chat/status` responde
`available: false` e a interface esconde a aba, com o resto do app intacto.

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

## A página do artista

Cada nome na lista de artistas de uma playlist abre uma página própria, montada
de quatro fontes e sem nenhuma chamada nova ao Spotify além de uma:

| Seção | Fonte | Custo |
|---|---|---|
| Foto, nome, link | Spotify `/artists/{id}` | 1 chamada, cache de 1 h |
| Biografia, tags, ouvintes, parecidos | Last.fm `artist.getInfo` | 1 chamada, cache de 24 h |
| Mais tocadas (com prévia tocável) | Deezer `/artist/{id}/top` | 2 chamadas, cache de 24 h |
| "No seu acervo" | `profile_store` em disco | nenhuma |

O id do artista **já vinha** na resposta das faixas da playlist (`artists(id,name)`)
e era descartado; guardá-lo é o que liga a lista à página sem uma busca por nome,
que erraria em artistas homônimos.

"No seu acervo" é um índice reverso `id do artista -> faixas` montado a partir dos
resumos em disco e refeito só quando o acervo muda (a assinatura é a quantidade de
arquivos e o mtime mais recente). Um artista parecido que também está no seu acervo
vira link interno; o resto aponta para o Last.fm — resolver o id de cada parecido
pela busca do Spotify custaria uma chamada por nome, oito por página.

A desambiguação no Deezer olha o número de fãs, não a ordem de relevância: o
catálogo tem entradas duplicadas com o mesmo nome exato, e a primeira costuma ser a
vazia — foi o que devolveu uma lista em branco para um artista com 278 mil ouvintes.

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

A aba **Perfil** agrega a conta inteira: artistas e gêneros mais presentes,
variedade de gosto, décadas, quando você adiciona músicas, faixas que se
repetem entre playlists e uma tabela comparando as playlists lado a lado. Só
entram playlists que o Spotify deixa ler (suas e colaborativas).

Abrir o perfil não chama o Spotify. O painel sai do que já existe:

1. **Resumos em disco** (`backend/.profile_cache/`): toda análise feita no app —
   abrir uma playlist ou a varredura da conta — grava um resumo compacto da
   playlist. Ele vale enquanto o `snapshot_id` do Spotify não muda e sobrevive a
   reinícios.
2. **O índice da busca**: enquanto faltam resumos, artistas e estilos de todas
   as faixas já indexadas aparecem num painel à parte, sem chamada nenhuma.
3. **O botão "Analisar as que faltam"** dispara a varredura da conta, com a
   estimativa de chamadas e de tempo antes de começar. Ela pula o Deezer (BPM e
   prévia), que sozinho levaria minutos numa conta inteira; o BPM médio usa as
   faixas que já têm BPM.

Enquanto a varredura roda, a página acompanha o progresso e recarrega o painel a
cada playlist concluída.

Análises simultâneas da mesma playlist (página + varredura) viram uma só.

## Várias contas

O login sempre foi por usuário (OAuth com PKCE, tokens num cookie de sessão
assinado que o JavaScript não lê). O que não era por usuário é o **estado do
servidor** — e é aí que dois usuários se enxergariam:

| Estado | Como é separado |
|---|---|
| Índice da busca (Chroma) | Id do documento é `{conta}:{faixa}` e toda consulta filtra por `owner` |
| Cache da análise de playlist | Chave `{conta}:{playlist}`, dentro de `build_playlist_analysis` |
| Análises em voo (dedupe) | Chave `(conta, playlist, com_áudio)` |
| Estado da varredura | Chave `{conta}:{playlist}` no `indexed_playlists.json` |
| Listagem de playlists em disco | Nome do arquivo com o hash da conta |
| Estatísticas do índice no perfil | Cache por conta |
| "No seu acervo", na página do artista | Filtrado pelas playlists que o Spotify acabou de listar |

A identidade vem de uma função só, `auth.user_key()`, e é o id do Spotify.
Existir em um lugar só é o ponto: um caminho novo que precise separar contas não
tem como inventar a própria chave e escapar do filtro sem querer.

Duas barreiras no índice, de propósito. O prefixo no id impede que o `upsert`
de uma conta sobrescreva a faixa de outra — duas pessoas podem ter a mesma
música, e com o id sendo só o da faixa a segunda apagava a da primeira. O
`where` impede que a busca por vizinho mais próximo, que varre a coleção
inteira, devolva a faixa de um estranho.

**Migração, não reindexação.** O índice e o estado da varredura já existiam sem
dono. Reindexar significaria reanalisar playlists no Spotify — exatamente o que
já rendeu uma suspensão de 18 horas. Então os dois são adotados no lugar:
o índice reaproveita os embeddings já gravados (nada recalcula, nada vai à
rede) e o estado tem as chaves reescritas. Quem chega primeiro adota tudo;
não há como saber de quem era, e numa instalação nova não existe legado.

### O que ainda falta para produção

O que está aqui torna o app **correto** para várias contas. Para colocá-lo na
internet ainda faltam decisões de infraestrutura:

- `ENVIRONMENT=production` liga o cookie só-HTTPS e recusa subir com o
  `SESSION_SECRET` de exemplo — mas ainda é preciso um proxy com TLS na frente.
- Os tokens moram dentro do cookie. Não dá para revogar uma sessão, e trocar o
  segredo desloga todo mundo. Multiusuário de verdade pede um id opaco e uma
  sessão do lado do servidor (Redis, banco).
- O estado é disco local (`.chroma`, `.profile_cache`, `.state`): uma instância
  só, sem escala horizontal.
- O bloqueio do Spotify é global do processo — um usuário pesado trava todos.
- Não há limite de requisições por usuário no próprio app.
- A cota do Spotify é um portão externo: apps em modo de desenvolvimento têm
  teto de usuários até você pedir a extensão de cota no dashboard.

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
(`127.0.0.1:5173`), com o índice vetorial num volume. O modelo de embeddings é
baixado durante o build da imagem, não no primeiro uso.

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
| `GET /artists/{id}/top-tracks` responde 403 | Página do artista ficaria sem "mais tocadas" | As mais tocadas vêm do Deezer (`/artist/{id}/top`), com capa e prévia |
| Campos `followers` e `popularity` removidos do objeto de artista | Sem número de audiência do Spotify | A audiência da página do artista é a do Last.fm (ouvintes e execuções) |

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
- **Cache**: em memória, TTL de um dia, por processo — reiniciar o backend zera.
  As exceções ficam em disco: os resumos do perfil (veja [Perfil](#perfil)), o
  bloqueio do Spotify e a última listagem de playlists (veja [Limites do Spotify](#limites-do-spotify)).
- **Dados faltando**: faixas locais e indisponíveis vêm com campos `null` (não
  ausentes), então o código usa `.get(x) or default` em vez de `.get(x, default)`.
- **Gráficos**: barras horizontais, uma cor por gráfico. Gênero é categoria
  nominal — colorir cada barra de um jeito duplicaria o comprimento na cor sem
  agregar informação. A cor das barras foi validada para contraste e banda de
  luminosidade sobre o fundo escuro.

## Limitações conhecidas / próximos passos

- **Uso pessoal / single-user**: a sessão fica num cookie, não há banco de
  usuários. Para publicar, seria preciso um session store real (Redis/DB) e
  revisar CORS/cookies para produção.
- **Cobertura de gênero**: artistas independentes ou pouco conhecidos podem não
  ter tags no Last.fm — isso aparece no contador de "músicas sem gênero
  identificado".
- **Chat**: o histórico vive no estado do React; recarregar a página zera a
  conversa. Não há persistência entre sessões.
- **Ideias de evolução**: ferramentas de busca e recomendação no agente;
  classificação por IA para as faixas que o Last.fm não cobre; comparar playlists
  entre si; exportar a análise.

## Testando rapidamente

```bash
# backend
cd backend && python -m py_compile app/*.py   # checagem de sintaxe rápida

# frontend
cd frontend && npm run build                   # garante que o build de produção funciona
```
