#!/bin/bash
set -e
set -x

export UWSGI_ROUTE_HOST="^(?!${NGINX}$) break:400"

cd /backend

if [[ ${INSTALL} == *"1"* ]]; then
  python3 -m pip install -r requirement.txt
fi

if [[ ${MIGRATE} == *"1"* ]]; then
  python3 manage.py collectstatic --noinput -i yes
  python3 manage.py makemigrations radio
  python3 manage.py migrate
fi

if [[ ${WAIT_SERVICE} == *"1"* ]]; then
  while ! nc ${WAIT_URL} ${WAIT_PORT}; do
    >&2 echo "Wait depends service - sleeping"
    sleep 1
  done
fi

if [[ ${AUTOSTART} == *"1"* ]]; then
  uwsgi --show-config
fi

exec "$@"

