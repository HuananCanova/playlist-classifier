# Playlist Classifier

Conecta com a sua conta do Spotify, lista suas playlists e gera gráficos de
gênero e subgênero — por playlist e por música.

- **Spotify Web API**: autenticação OAuth, suas playlists e as faixas de cada uma.
- **Last.fm API**: as tags da comunidade, que são a fonte de gênero do projeto —
  tags do **artista** dão o gênero amplo (`techno`, `mpb`), tags da **faixa** dão o
  subgênero (`minimal techno`, `bossa nova`), com granularidade por música.
- **Claude API**: um chat que responde perguntas sobre as suas playlists
  consultando os dados reais por meio de ferramentas (opcional).

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
│       ├── ai_tools.py        # as ferramentas do agente (neutras de provedor)
│       ├── ai_chat.py         # adaptador Claude + streaming SSE
│       ├── ai_chat_groq.py    # adaptador Groq (testes sem custo)
│       ├── chat.py            # rotas /api/chat
│       ├── models.py          # schemas Pydantic
│       └── cache.py           # cache em memória (TTL) pra não estourar rate limit
└── frontend/         React + Vite — login, lista de playlists, gráficos (Recharts)
    └── src/
        ├── App.jsx / AuthContext.jsx
        ├── pages/    Login, PlaylistList, PlaylistDetail, Chat
        └── components/  gráficos de barras, tabela de faixas, loader da análise
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

Indexar é efeito colateral de analisar uma playlist: os dados já foram buscados,
então **não custa nenhuma chamada externa a mais**. O índice cresce conforme você
navega, e nunca sozinho — o que importa num projeto que já levou ban do Spotify
por volume de requisições.

Consequência a assumir: a busca só enxerga o que você já abriu. Um resultado
vazio quase sempre quer dizer "essa playlist ainda não foi analisada", não "não
existe" — e a tela de busca diz quantas faixas estão indexadas, justamente para
essa diferença ficar clara.

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
e março de 2026 quebraram três suposições do projeto:

| Mudança | Efeito | Como o código lida |
|---|---|---|
| `GET /playlists/{id}/tracks` removido | 403 em toda análise | Usa `/playlists/{id}/items`; cada entrada agora é `item`, não `track` |
| Endpoints em lote removidos (`GET /artists?ids=`, `/tracks`, `/albums`…) | 403 ao buscar artistas | Busca individual por artista, com concorrência limitada + cache |
| Campo `genres` removido do objeto de artista | Spotify deixou de fornecer gênero | Gênero passou a vir das tags de artista do Last.fm |
| Contagem migrou de `tracks.total` para `items.total` | Toda playlist aparecia com 0 músicas | Lê `items.total` com fallback pro campo deprecado |

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
