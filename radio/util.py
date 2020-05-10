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


def get_pending_remove():
    pending_remove = redis_server.get('pending_remove')
    if pending_remove is None:
        default_data = {
            "list": None
        }
        redis_server.set('pending_remove', json.dumps(default_data, ensure_ascii=False).encode('utf-8'))
    try:
        data_json = json.loads(pending_remove)
    except Exception as e:
        print('redis error: {}'.format(e))
        return None
    return dict(data_json)


def set_pending_remove(remove_list):
    pending_remove = get_pending_remove()
    pending_remove["list"] = remove_list
    redis_server.set('pending_remove', json.dumps(pending_remove, ensure_ascii=False).encode('utf-8'))


def get_is_pending_remove(track_id):
    pending_remove = get_pending_remove()
    if pending_remove is None:
        return False
    else:
        pending_remove_list = pending_remove["list"]
        if pending_remove_list is not None:
            try:
                index = pending_remove_list.index(track_id)
            except ValueError:
                return False
            else:
                return True
        else:
            return False


def remove_pending_track():
    from .models import (
        Track
    )

    pending_remove = get_pending_remove()
    if pending_remove is None:
        pass
    else:
        pending_remove_list = pending_remove["list"]
        if pending_remove_list is not None:
            while pending_remove_list:
                track_id = pending_remove_list.pop()
                try:
                    track = Track.objects.get(id=track_id)
                except Track.DoesNotExist:
                    pass
                else:
                    if track:
                        delete_track(track, force=True)
        set_pending_remove(pending_remove_list)


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
    delta_10minute = timedelta(minutes=10)
    base_time = now - delta_3hour
    after_10minute = now - delta_10minute

    filters = Q(channel__icontains=channel)

    # Except now playing
    if now_play_track_id is not None:
        filters = filters and ~Q(id=now_play_track_id)

    # Except last play
    if last_play_track_id is not None and now_play_track_id != last_play_track_id:
        filters = filters and ~Q(id=last_play_track_id)

    tracks = Track.objects.filter(
        (Q(last_played_at__lt=base_time) | Q(last_played_at=None, uploaded_at__gt=after_10minute)) and filters)

    if tracks.count() < 1:
        # If service music is too few, ignore International Radio Law.
        tracks = Track.objects.filter(filters)

    count_track = tracks.count()
    if count_track > samples:
        count_track = samples
    random_tracks = random.sample(list(tracks), count_track)

    return random_tracks


def delete_track(track, force=False):
    # Remove from playlist
    channel_list = track.channel
    location = track.location
    for channel in channel_list:
        redis_data = get_redis_data(channel)
        if redis_data:
            if redis_data["now_playing"]:
                now_playing = redis_data["now_playing"]

                if int(now_playing["id"]) == track.id:
                    if not force:
                        pending_remove = get_pending_remove()
                        pending_remove_list = pending_remove["list"]
                        if not get_is_pending_remove(track.id):
                            if pending_remove_list is None:
                                pending_remove_list = [track.id]
                            else:
                                pending_remove_list.append(track.id)
                            set_pending_remove(pending_remove_list)
                            raise ValidationError(_(
                                "Pending remove reserved for '{0} - {1}' beacuse current playing".format(
                                    track.artist, track.title
                                )
                            ))
                        else:
                            raise ValidationError(_("Already pending remove reserved"))

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
