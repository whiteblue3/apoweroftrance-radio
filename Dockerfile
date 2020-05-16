FROM python:3.6-slim AS build
MAINTAINER @whiteblue3 https://github.com/whiteblue3

RUN mkdir /backend
WORKDIR /backend

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY ./apoweroftrance-django-utils-0.0.1.tar.gz /backend/apoweroftrance-django-utils-0.0.1.tar.gz
COPY ./apoweroftrance-account-0.0.1.tar.gz /backend/apoweroftrance-account-0.0.1.tar.gz
COPY ./requirement.txt /backend/requirement.txt

RUN apt-get update && apt-get -y install --no-install-recommends build-essential \
    && python3 -m pip install --upgrade pip setuptools wheel \
    && python3 -m pip install --no-cache-dir uwsgi==2.0.18 \
    && python3 -m pip install --no-cache-dir -r requirement.txt \
    && apt-get remove --purge -y build-essential \
    && apt-get -y autoremove \
    && apt-get -y clean \
    && rm -f /var/cache/apt/archives/*.rpm /var/cache/apt/*.bin /var/lib/apt/lists/*.*;


FROM python:3.6-slim AS deploy
MAINTAINER @whiteblue3 https://github.com/whiteblue3

COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

ENV PYTHONUNBUFFERED 0
ENV TZ=Asia/Seoul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update && apt-get -y install --no-install-recommends vim netcat-openbsd

ENV NGINX=127.0.0.1:80

ENV DJANGO_SETTINGS_MODULE=app.settings
ENV UWSGI_WSGI_FILE=/backend/app/wsgi.py
#ENV UWSGI_SOCKET=/backend/app.sock UWSGI_CHMOD_SOCKET=644
#ENV UWSGI_HTTP=0.0.0.0:8090
ENV UWSGI_SOCKET=0.0.0.0:8090 UWSGI_CHMOD_SOCKET=644
ENV UWSGI_LAZY_APPS=1 UWSGI_WSGI_ENV_BEHAVIOR=holy UWSGI_POST_BUFFERING=1
ENV UWSGI_MASTER=1 UWSGI_HTTP_AUTO_CHUNKED=1 UWSGI_HTTP_KEEPALIVE=1 UWSGI_PROCESS=4
ENV UWSGI_STATIC_MAP="/static/=/backend/.static/" UWSGI_STATIC_EXPIRES_URI="/static/.*\.[a-f0-9]{12,}\.(css|js|png|jpg|jpeg|gif|ico|woff|ttf|otf|svg|scss|map|txt) 315360000"
#ENV UWSGI_ROUTE_HOST="^(?!${NGINX}$) break:400"

EXPOSE 8090

ENV USER=ubuntu
RUN useradd -rm -d /home/${USER} -s /bin/bash --no-log-init ${USER}

RUN chown -R ${USER}:${USER} /opt/venv

WORKDIR /backend
RUN chown -R ${USER}:${USER} /backend

COPY ./startup.sh /backend/startup.sh
RUN chmod a+x /backend/startup.sh

# it uses for gcs cloud storage
ENV GOOGLE_APPLICATION_CREDENTIALS /etc/gcloud/service-account-key.json

RUN mkdir -p /etc/gcloud

ENV ENABLE_SWAGGER 1

ENV DB_NAME 'apoweroftrance'
ENV DB_HOST '127.0.0.1'
ENV DB_USERNAME 'postgres'
ENV DB_PASSWORD ''
ENV DB_PORT 5432

ENV REDIS_URL "127.0.0.1"
ENV REDIS_PORT 6379
ENV REDIS_DB 0

###########################
# service depends control #

# if 1, wait to start the depends service is up
ENV WAIT_SERVICE 0
ENV WAIT_URL "127.0.0.1"
ENV WAIT_PORT 5432

###################
# startup control #

# pip install when start (dev usally)
ENV INSTALL 0

# pip makemigrations and migrate (dev usally)
ENV MIGRATE 0

# automatic start django
ENV AUTOSTART 1


# Uncommend when production
FROM deploy AS production
MAINTAINER @whiteblue3 https://github.com/whiteblue3
COPY . /backend/
RUN chown -R ${USER}:${USER} /backend
RUN rm requirement.txt && rm Dockerfile && rm build_push_docker_image.sh && rm -rf .git && rm -rf .gitignore \
    && rm apoweroftrance-django-utils-0.0.1.tar.gz && rm apoweroftrance-account-0.0.1.tar.gz \
    && rm -rf apoweroftrance_radio.egg-info && rm -rf build && rm -rf dist && rm package.sh


USER ${USER}
ENTRYPOINT ["./startup.sh"]