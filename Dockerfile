FROM python:3.12-slim
WORKDIR /srv
COPY server/ ./server/
COPY web/ ./web/
ENV PORT=8099 DATA_DIR=/data RAW_DAYS=90
VOLUME /data
EXPOSE 8099
CMD ["python3", "server/app.py"]
