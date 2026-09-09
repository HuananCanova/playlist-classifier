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
COPY pytest.ini ./

# O índice vetorial mora aqui; monte um volume para ele sobreviver ao container.
VOLUME ["/srv/.chroma"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
