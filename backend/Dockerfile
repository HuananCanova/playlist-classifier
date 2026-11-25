# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /srv

# Dependências antes do código: o cache de camadas do Docker só é reaproveitado
# se o requirements.txt não mudou, e ele muda muito menos que o app.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Baixa o modelo de embeddings (~80 MB) na hora de construir a imagem, não na
# primeira busca. Sem isso, o primeiro usuário depois de cada `docker run`
# esperaria o download — e um container sem rede simplesmente não buscaria.
RUN python -c "from chromadb.utils import embedding_functions; embedding_functions.DefaultEmbeddingFunction()"

COPY app ./app
COPY evals ./evals
COPY tests ./tests
# Ferramentas de manutenção precisam rodar ONDE o dado está — os volumes do
# container. `scripts/reclassificar_generos.py` reclassifica gênero no banco
# sem rede, e sem isto só daria para rodá-lo no banco da máquina de quem
# desenvolve, que não é o que o app serve.
COPY scripts ./scripts
COPY pytest.ini ./

# Índice vetorial e banco SQLite; monte volumes para sobreviverem ao container.
VOLUME ["/srv/.chroma", "/srv/.data"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
