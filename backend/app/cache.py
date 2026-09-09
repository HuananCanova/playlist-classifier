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
