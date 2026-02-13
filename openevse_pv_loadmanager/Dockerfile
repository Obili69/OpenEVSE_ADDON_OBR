ARG BUILD_FROM
FROM ${BUILD_FROM}

WORKDIR /opt

COPY app/ /opt/app/
COPY rootfs/ /

RUN pip install --no-cache-dir aiomqtt
