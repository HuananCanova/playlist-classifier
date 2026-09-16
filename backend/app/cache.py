"""Simple process-wide TTL caches to avoid hammering Last.fm for data that barely
changes (artist and track tags). Fine for a single-user local app; swap for Redis
if this ever needs to run multi-process.
"""
from cachetools import TTLCache

# Last.fm tags for an artist (the broad genre) — cache for a day.
artist_tags_cache: TTLCache = TTLCache(maxsize=5000, ttl=60 * 60 * 24)

# Last.fm tags for a track (the subgenre) — cache for a day too.
track_tags_cache: TTLCache = TTLCache(maxsize=10000, ttl=60 * 60 * 24)

# Correspondência de faixa no Deezer (BPM + preview). A URL do preview é
# assinada e expira, então o TTL aqui é curto de propósito.
deezer_cache: TTLCache = TTLCache(maxsize=5000, ttl=60 * 30)

# Detalhe pronto da faixa. O TTL fica logo abaixo do `deezer_cache` de
# propósito: o objeto carrega a `preview_url` assinada do Deezer, então
# guardá-lo por mais tempo que a própria URL serviria um link já morto.
track_detail_cache: TTLCache = TTLCache(maxsize=5000, ttl=60 * 25)

# Análise pronta de uma playlist. Existe porque o chat agora tem duas
# ferramentas por escopo: sem o cache, analisar e depois buscar dentro da mesma
# playlist refaria toda a varredura de Spotify + Last.fm no mesmo turno.
playlist_analysis_cache: TTLCache = TTLCache(maxsize=200, ttl=60 * 10)
# Deezer (BPM + prévia) — dado estável, mesmo TTL de um dia.
deezer_track_cache: TTLCache = TTLCache(maxsize=10000, ttl=60 * 60 * 24)

# A lista de playlists do usuário — TTL curto porque ela muda quando ele mexe
# no Spotify, mas recarregar a página não pode custar uma chamada nova.
# É a única API do app com rate limit severo, e era a única sem cache.
user_playlists_cache: TTLCache = TTLCache(maxsize=64, ttl=60 * 5)

# `artist.getInfo` do Last.fm (bio, audiência, tags, parecidos) — dado
# estável, mesmo TTL de um dia das outras consultas ao Last.fm.
artist_info_cache: TTLCache = TTLCache(maxsize=5000, ttl=60 * 60 * 24)

# Página do artista já montada (Spotify + Last.fm + acervo). TTL de uma hora:
# nada ali muda de minuto a minuto, e a página é reaberta ao navegar entre
# artistas parecidos.
artist_profile_cache: TTLCache = TTLCache(maxsize=1000, ttl=60 * 60)

# Mais tocadas de um artista no Deezer. Dado estável e a busca por nome custa
# duas requisições, então vale um TTL longo.
deezer_artist_cache: TTLCache = TTLCache(maxsize=2000, ttl=60 * 60 * 24)
