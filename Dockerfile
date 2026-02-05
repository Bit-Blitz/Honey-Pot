FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data

EXPOSE 7860

CMD ["gunicorn", "--bind", "0.0.0.0:7860", "app.main:app"]