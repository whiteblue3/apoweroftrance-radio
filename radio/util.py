import os
import random
import json
import redis
from datetime import datetime, timedelta
from dateutil.tz import tzlocal
from django.db.models import Q
from django_utils import storage
from django.utils.translation import ugettext_lazy as _
from google.api_core.exceptions import NotFound
from rest_framework.exceptions import ValidationError


redis_host = os.environ.get('REDIS_URL')
redis_port = os.environ.get('REDIS_PORT')
redis_db = os.environ.get('REDIS_DB')
redis_server = redis.StrictRedis(host=redis_host, port=redis_port, db=redis_db)


NUM_SAMPLES = 21


def now():
    return str(datetime.now(tz=tzlocal()).isoformat())


def get_redis_data(channel):
    raw_json = redis_server.get(channel)
    if raw_json is None:
        default_data = {
            "now_playing": None,
            "playlist": None
        }
        redis_server.set(channel, json.dumps(default_data, ensure_ascii=False).encode('utf-8'))
    try:
        data_json = json.loads(raw_json)
    except Exception as e:
        print('redis error: {}'.format(e))
        return None
    return dict(data_json)


def set_redis_data(channel, key, value):
    redis_data = get_redis_data(channel)
    redis_data[key] = value
    redis_server.set(channel, json.dumps(redis_data, ensure_ascii=False).encode('utf-8'))


def get_random_track(channel, samples):
    from .models import (
        Track
    )

    # Remove last played track from queue
    now_play_track_id = None
    last_play_track_id = None
    try:
        redis_data = get_redis_data(channel)
        now_playing = redis_data["now_playing"]
        playlist = redis_data["playlist"]
    except IndexError:
        pass
    else:
        try:
            if now_playing:
                now_play_track_id = now_playing["id"]
        except KeyError:
            pass

        try:
            if playlist:
                last_play_track_id = playlist[-1]["id"]
        except KeyError:
            pass
        except IndexError:
            pass

    # According to International Radio Law, Once played track cannot restream in 3 hours
    now = datetime.now(tz=tzlocal())
    delta_3hour = timedelta(hours=3)
    base_time = now - delta_3hour

    filters = Q(channel__icontains=channel)

    # Except now playing
    if now_play_track_id is not None:
        filters = filters and ~Q(id=now_play_track_id)

    # Except last play
    if last_play_track_id is not None and now_play_track_id != last_play_track_id:
        filters = filters and ~Q(id=last_play_track_id)

    tracks = Track.objects.filter(
        (Q(last_played_at__lt=base_time) | Q(last_played_at=None)) and filters)

    if tracks.count() < 1:
        # If service music is too few, ignore International Radio Law.
        tracks = Track.objects.filter(filters)

    count_track = tracks.count()
    if count_track > samples:
        count_track = samples
    random_tracks = random.sample(list(tracks), count_track)

    return random_tracks


def delete_track(track):
    # Remove from playlist
    channel_list = track.channel
    location = track.location
    for channel in channel_list:
        redis_data = get_redis_data(channel)
        if redis_data:
            if redis_data["now_playing"]:
                now_playing = redis_data["now_playing"]

                if int(now_playing["id"]) == track.id:
                    raise ValidationError(_("Music cannot delete because now playing"))

            if redis_data["playlist"]:
                playlist = redis_data["playlist"]

                for music in playlist:
                    if int(music["id"]) == track.id:
                        index = playlist.index(music)
                        playlist.pop(index)

                set_redis_data(channel, "playlist", playlist)

    try:
        location_split = location.split("/")

        storage_driver = 'gcs'
        storage.delete_file('music', location_split[-1], storage_driver)
    except NotFound:
        pass

    track.delete()
