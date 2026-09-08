"""Simple process-wide TTL caches to avoid hammering Last.fm for data that barely
changes (artist and track tags). Fine for a single-user local app; swap for Redis
if this ever needs to run multi-process.
"""
from cachetools import TTLCache

# Last.fm tags for an artist (the broad genre) — cache for a day.
artist_tags_cache: TTLCache = TTLCache(maxsize=5000, ttl=60 * 60 * 24)

# Last.fm tags for a track (the subgenre) — cache for a day too.
track_tags_cache: TTLCache = TTLCache(maxsize=10000, ttl=60 * 60 * 24)

# Deezer (BPM + prévia) — dado estável, mesmo TTL de um dia.
deezer_track_cache: TTLCache = TTLCache(maxsize=10000, ttl=60 * 60 * 24)

# A lista de playlists do usuário — TTL curto porque ela muda quando ele mexe
# no Spotify, mas recarregar a página não pode custar uma chamada nova.
# É a única API do app com rate limit severo, e era a única sem cache.
user_playlists_cache: TTLCache = TTLCache(maxsize=64, ttl=60 * 5)

# Faixas e metadados de uma playlist, para reanalisar sem repaginar tudo.
playlist_tracks_cache: TTLCache = TTLCache(maxsize=256, ttl=60 * 15)
