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
│       ├── ai_chat.py         # agente Claude + tools (streaming SSE)
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
  agente Claude ──chama──> listar_playlists()    ──> Spotify
      ↓                    analisar_playlist(id) ──> Spotify + Last.fm
  resposta em streaming (SSE)
```

Por que assim:

- **Extensibilidade**: adicionar busca ou recomendação é registrar uma ferramenta
  nova em `build_tools()`. Nada mais no arquivo muda.
- **Sem alucinação de dados**: o modelo não tem como inventar uma playlist que
  não existe, porque os nomes e números vêm da ferramenta.
- **Custo controlado**: cada ferramenta tem teto de tamanho. Uma playlist de 300
  faixas devolve ~1.300 tokens (15 gêneros, 10 artistas, amostra de 40 faixas), e
  o resultado avisa ao modelo que é uma amostra — em vez de despejar as 300.
- **Credencial fora do alcance do modelo**: o token do Spotify fica capturado no
  closure das ferramentas, não como parâmetro delas.

O chat é opcional: sem `ANTHROPIC_API_KEY`, o `/api/chat/status` responde
`available: false` e a interface esconde a aba, com o resto do app intacto.

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

### 3. (Opcional) Chave da Anthropic, para o chat

Crie uma em https://console.anthropic.com/settings/keys e coloque em
`ANTHROPIC_API_KEY` no `backend/.env`. Sem ela o app funciona normalmente, só
sem a aba de chat.

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
