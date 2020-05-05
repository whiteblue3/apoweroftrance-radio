#!/bin/bash

APP_NAME=radio
VERSION=0.0.16

docker build --no-cache=True -t ${APP_NAME}:${VERSION} .
docker tag ${APP_NAME}:${VERSION} gcr.io/apoweroftrance/${APP_NAME}:${VERSION}
docker tag ${APP_NAME}:${VERSION} gcr.io/apoweroftrance/${APP_NAME}:latest
gcloud docker -- push gcr.io/apoweroftrance/${APP_NAME}:${VERSION}
gcloud docker -- push gcr.io/apoweroftrance/${APP_NAME}:latest

