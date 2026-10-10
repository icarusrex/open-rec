FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --uid 2000 --create-home openrec
USER openrec

CMD ["open-rec", "run"]
