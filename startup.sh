#!/bin/sh
set -e
set -x

export UWSGI_ROUTE_HOST="^(?!${NGINX}$) break:400"

cd /backend

## Dev only

#python3 -m pip install -r requirement.txt
#python3 manage.py collectstatic --noinput -i yes
#python3 manage.py makemigrations radio
#python3 manage.py migrate


## Uncomment when production

#while ! nc ${DB_HOST} ${DB_PORT}; do
#  >&2 echo "Wait database service - sleeping"
#  sleep 1
#done
#uwsgi --show-config
exec "$@"

