ARG BUILD_FROM
FROM ${BUILD_FROM}

WORKDIR /opt

COPY app/ /opt/app/

RUN pip install --no-cache-dir aiomqtt

CMD ["python3", "-m", "app.main"]
