import json
from datetime import datetime, timedelta
from django.core.cache import cache
from django.conf import settings
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.utils.datastructures import MultiValueDictKeyError
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.cache import never_cache
from django.db import transaction
from django.db.models import Q
from django.utils.translation import ugettext_lazy as _
from rest_framework import mixins, generics
from rest_framework.exceptions import ValidationError
from rest_framework.generics import RetrieveAPIView, CreateAPIView, DestroyAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser, IsAuthenticatedOrReadOnly
from rest_framework.renderers import JSONRenderer
from rest_framework.serializers import Serializer
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework import status
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django_utils import api, storage
from django_utils.api import method_permission_classes
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.easyid3 import EasyID3
from .models import (
    SUPPORT_FORMAT, FORMAT_MP3, FORMAT_M4A, SERVICE_CHANNEL, CHANNEL,
    Track, Like
)
from .serializers import (
    TrackSerializer, TrackAPISerializer, LikeSerializer, LikeAPISerializer,
    PlayQueueSerializer, PlayHistorySerializer
)
from .util import (
    now, get_random_track, get_redis_data, set_redis_data, delete_track, remove_pending_track, get_is_pending_remove,
    NUM_SAMPLES
)


@never_cache
def upload_progress(request):
    """
    Used by Ajax calls
    Return the upload progress and total length values
    """
    if 'X-Progress-ID' in request.GET:
        progress_id = request.GET['X-Progress-ID']
    elif 'X-Progress-ID' in request.META:
        progress_id = request.META['X-Progress-ID']
    else:
        progress_id = None

    if progress_id:
        cache_key = "%s_%s" % (request.META['REMOTE_ADDR'], progress_id)
        data = cache.get(cache_key)
        return HttpResponse(json.dumps(data))


class TrackListAPI(RetrieveAPIView):
    manual_parameters = [
        openapi.Parameter(
            name="keyword",
            in_=openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            required=False,
            description="Keyword",
            default=None
        ),
        openapi.Parameter(
            name="page",
            in_=openapi.IN_QUERY,
            type=openapi.TYPE_INTEGER,
            required=True,
            description="Page number",
            default=0
        ),
        openapi.Parameter(
            name="limit",
            in_=openapi.IN_QUERY,
            type=openapi.TYPE_INTEGER,
            required=True,
            description="Limit per page",
            default=30
        ),
    ]
    permission_classes = (AllowAny,)
    renderer_classes = (JSONRenderer,)
    serializer_class = Serializer

    @swagger_auto_schema(
        operation_summary="Search Music List",
        operation_description="Public API. Search music. if keyword is black or null, search entire music list",
        manual_parameters=manual_parameters,
        responses={'200': TrackSerializer})
    @transaction.atomic
    @method_decorator(ensure_csrf_cookie)
    def get(self, request, *args, **kwargs):
        try:
            keyword = request.GET["keyword"]
        except MultiValueDictKeyError:
            keyword = None

        try:
            page = int(request.GET["page"])
        except MultiValueDictKeyError:
            page = 0

        try:
            limit = int(request.GET["limit"])
        except MultiValueDictKeyError:
            limit = 30

        if keyword is None:
            queryset = Track.objects.filter(Q(is_service=True))
        else:
            queryset = Track.objects.filter(
                Q(is_service=True) | Q(title__icontains=keyword) | Q(artist__icontains=keyword)
            )

        track_list = queryset.order_by('-uploaded_at').distinct()[(page * limit):((page * limit) + limit)]
        response = []

        for track in track_list:
            is_pending_remove = get_is_pending_remove(track.id)
            if is_pending_remove:
                continue
            serializer = TrackSerializer(track)
            response.append(serializer.data)

        return api.response_json(response, status.HTTP_200_OK)


class UploadAPI(CreateAPIView):
    manual_parameters = [
        openapi.Parameter(
            name="audio",
            in_=openapi.IN_FORM,
            type=openapi.TYPE_FILE,
            required=True,
            description="Music File"
        ),
        openapi.Parameter(
            name="format",
            in_=openapi.IN_FORM,
            type=openapi.TYPE_STRING,
            required=True,
            description="File Format",
            enum=SUPPORT_FORMAT
        ),
        openapi.Parameter(
            name="artist",
            in_=openapi.IN_FORM,
            type=openapi.TYPE_STRING,
            required=True,
            description="Artist"
        ),
        openapi.Parameter(
            name="title",
            in_=openapi.IN_FORM,
            type=openapi.TYPE_STRING,
            required=True,
            description="Music Title"
        ),
        openapi.Parameter(
            name="description",
            in_=openapi.IN_FORM,
            type=openapi.TYPE_STRING,
            required=False,
            description="Music Description"
        ),
        openapi.Parameter(
            name="bpm",
            in_=openapi.IN_FORM,
            type=openapi.TYPE_INTEGER,
            required=False,
            description="BPM"
        ),
        openapi.Parameter(
            name="scale",
            in_=openapi.IN_FORM,
            type=openapi.TYPE_STRING,
            required=False,
            description="Music Scale"
        ),
        openapi.Parameter(
            name="channel",
            in_=openapi.IN_FORM,
            type=openapi.TYPE_ARRAY,
            required=True,
            description="Service Channel",
            items=openapi.Items(type=openapi.TYPE_STRING, enum=SERVICE_CHANNEL)
        ),
    ]

    permission_classes = (IsAuthenticated,)
    renderer_classes = (JSONRenderer,)
    parser_classes = (MultiPartParser, FormParser,)
    serializer_class = Serializer

    @swagger_auto_schema(
        operation_summary="Upload Music",
        operation_description="Authentication required",
        manual_parameters=manual_parameters,
        operation_id='upload_music',
        responses={'201': TrackSerializer})
    @transaction.atomic
    @method_decorator(ensure_csrf_cookie)
    def post(self, request, *args, **kwargs):
        user = request.user

        if len(request.FILES.getlist('audio')) > 1:
            raise ValidationError(_("You must select ONE file"))
        elif len(request.FILES.getlist('audio')) < 1:
            raise ValidationError(_("You must select music file"))

        try:
            audio_format = request.data["format"]
        except MultiValueDictKeyError:
            raise ValidationError(_("Please select file format"))

        if audio_format not in SUPPORT_FORMAT:
            raise ValidationError(_("Unsupported music file format"))

        try:
            artist = request.data["artist"]
        except MultiValueDictKeyError:
            raise ValidationError(_("'artist' is required"))

        if len(artist) > 70:
            raise ValidationError(_("'artist' size is under 70"))

        try:
            title = request.data["title"]
        except MultiValueDictKeyError:
            raise ValidationError(_("'title' is required"))

        if len(title) > 200:
            raise ValidationError(_("'title' size is under 200"))

        try:
            description = request.data["description"]
        except MultiValueDictKeyError:
            description = ""

        try:
            bpm = int(request.data["bpm"])
        except MultiValueDictKeyError:
            bpm = None

        try:
            scale = request.data["scale"]
        except MultiValueDictKeyError:
            scale = None

        if len(scale) > 15:
            raise ValidationError(_("'scale' size is under 15"))

        try:
            channel = request.data["channel"]
        except MultiValueDictKeyError:
            raise ValidationError(_("'channel' is required"))

        channel = channel.replace('"', '').split(',')

        for service_channel in channel:
            if service_channel not in SERVICE_CHANNEL:
                raise ValidationError(_("Invalid service channel"))

        duration = None
        filepath = None
        for f in request.FILES.getlist('audio'):
            try:
                storage_driver = settings.STORAGE_DRIVER
                valid_mimetype = None
                if audio_format == FORMAT_MP3:
                    valid_mimetype = [
                        "audio/mpeg", "audio/mp3"
                    ]
                elif audio_format == FORMAT_M4A:
                    valid_mimetype = [
                        "audio/aac", "audio/x-m4a", "audio/mp4", "audio/m4a"
                    ]
                if valid_mimetype is not None:
                    filepath = storage.upload_file_direct(f, 'music', storage_driver, valid_mimetype)
                else:
                    raise ValidationError(_("Unsupported music file format"))
            except Exception as e:
                raise e

            if audio_format == FORMAT_MP3:
                audio = MP3(f, ID3=EasyID3)
                duration = audio.info.length

            elif audio_format == FORMAT_M4A:
                audio = MP4(f)
                duration = audio.info.length

        if filepath is not None and duration is not None:
            serializer = TrackSerializer(
                data={
                    "user_id": user.id,
                    "location": filepath,
                    "format": audio_format,
                    "is_service": True,
                    "artist": artist,
                    "title": title,
                    "description": description,
                    "bpm": bpm,
                    "scale": scale,
                    "duration": str(timedelta(seconds=float(duration))),
                    "play_count": 0,
                    "channel": channel,
                    "uploaded_at": now(),
                    "last_played_at": None
                }
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
        else:
            raise ValidationError(_("Music upload failed"))

        return api.response_json(serializer.data, status.HTTP_201_CREATED)


class TrackAPI(
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    generics.GenericAPIView
):
    permission_classes = (IsAuthenticatedOrReadOnly,)
    renderer_classes = (JSONRenderer,)
    serializer_class = TrackAPISerializer

    @swagger_auto_schema(
        operation_summary="View music information",
        operation_description="Public API",
        responses={'200': TrackSerializer})
    @transaction.atomic
    @method_decorator(ensure_csrf_cookie)
    @method_permission_classes((AllowAny,))
    def get(self, request, track_id, *args, **kwargs):
        try:
            track = Track.objects.get(id=track_id)
        except Track.DoesNotExist:
            raise ValidationError(_("Music does not exist"))

        is_pending_remove = get_is_pending_remove(track_id)
        if is_pending_remove:
            raise ValidationError(_("You cannot view track information because the track is reserved pending remove"))

        serializer = TrackSerializer(track)

        return api.response_json(serializer.data, status.HTTP_200_OK)

    @swagger_auto_schema(
        operation_summary="Modify music information",
        operation_description="Authentication required. Modify my own music information",
        responses={'202': TrackSerializer})
    @transaction.atomic
    @method_decorator(ensure_csrf_cookie)
    @method_permission_classes((IsAuthenticated,))
    def put(self, request, track_id, *args, **kwargs):
        user = request.user

        try:
            track = Track.objects.get(id=track_id)
        except Track.DoesNotExist:
            raise ValidationError(_("Music does not exist"))

        is_pending_remove = get_is_pending_remove(track_id)
        if is_pending_remove:
            raise ValidationError(_("You cannot edit music information because the track is reserved pending remove"))

        if track.user.id == user.id:
            serializer = TrackSerializer(track, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
        else:
            raise ValidationError(_("You have NOT permission to modify track information"))

        return api.response_json(serializer.data, status.HTTP_202_ACCEPTED)

    @swagger_auto_schema(
        operation_summary="Delete music",
        operation_description="Authentication required. Delete my own music",
        responses={'202': "OK"})
    @transaction.atomic
    @method_decorator(ensure_csrf_cookie)
    @method_permission_classes((IsAuthenticated,))
    def delete(self, request, track_id, *args, **kwargs):
        user = request.user

        try:
            track = Track.objects.get(id=track_id)
        except Track.DoesNotExist:
            raise ValidationError(_("Music does not exist"))

        is_pending_remove = get_is_pending_remove(track_id)
        if is_pending_remove:
            raise ValidationError(_("Track is already reserved pending remove"))

        if track.user.id == user.id:
            delete_track(track)
        else:
            raise ValidationError(_("You have NOT permission to delete track"))

        return api.response_json("OK", status.HTTP_202_ACCEPTED)


class LikeAPI(CreateAPIView):
    permission_classes = (IsAuthenticated,)
    renderer_classes = (JSONRenderer,)
    serializer_class = LikeAPISerializer

    @swagger_auto_schema(
        operation_summary="Like, Unlike or not both the music",
        operation_description="Authentication required",
        responses={'200': LikeSerializer})
    @transaction.atomic
    @method_decorator(ensure_csrf_cookie)
    def post(self, request, track_id, *args, **kwargs):
        user = request.user
        try:
            like_value = request.data["like"]
        except MultiValueDictKeyError:
            like_value = None

        try:
            _ = Track.objects.get(id=track_id)
        except Track.DoesNotExist:
            raise ValidationError(_("Music does not exist"))

        is_pending_remove = get_is_pending_remove(track_id)
        if is_pending_remove:
            raise ValidationError(_("You can't do it because the track is reserved pending remove"))

        try:
            like = Like.objects.get(track_id=track_id, user_id=user.id)
        except Like.DoesNotExist:
            serializer = LikeSerializer(data={
                "track_id": track_id,
                "user_id": user.id,
                "like": like_value,
                "updated_at": now()
            })
        else:
            serializer = LikeSerializer(like, data={
                "track_id": track_id,
                "user_id": user.id,
                "like": like_value,
                "updated_at": now()
            })
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return api.response_json(serializer.data, status.HTTP_200_OK)


class PlayQueueAPI(RetrieveAPIView):
    manual_parameters = [
        openapi.Parameter(
            name="channel",
            in_=openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            required=True,
            description="Service Channel",
            enum=SERVICE_CHANNEL
        ),
        openapi.Parameter(
            name="page",
            in_=openapi.IN_QUERY,
            type=openapi.TYPE_INTEGER,
            required=True,
            description="Page number",
            default=0
        ),
        openapi.Parameter(
            name="limit",
            in_=openapi.IN_QUERY,
            type=openapi.TYPE_INTEGER,
            required=True,
            description="Limit per page",
            default=30
        ),
    ]
    permission_classes = (AllowAny,)
    renderer_classes = (JSONRenderer,)
    serializer_class = Serializer

    @swagger_auto_schema(
        operation_summary="Play List",
        operation_description="Public API",
        manual_parameters=manual_parameters,
        responses={'200': PlayQueueSerializer})
    @transaction.atomic
    @method_decorator(ensure_csrf_cookie)
    def get(self, request, *args, **kwargs):
        try:
            channel = request.GET["channel"]
        except MultiValueDictKeyError:
            raise ValidationError(_("'channel' is required parameter"))

        if channel not in SERVICE_CHANNEL:
            raise ValidationError(_("Invalid service channel"))

        try:
            page = int(request.GET["page"])
        except MultiValueDictKeyError:
            page = 0

        try:
            limit = int(request.GET["limit"])
        except MultiValueDictKeyError:
            limit = 30

        redis_data = get_redis_data(channel)
        if redis_data:
            playlist = redis_data["playlist"]
            if playlist:
                return api.response_json(playlist[(page * limit):((page * limit) + limit)], status.HTTP_200_OK)
            else:
                return api.response_json(None, status.HTTP_200_OK)

        return api.response_json(None, status.HTTP_200_OK)


class ChannelNameAPI(RetrieveAPIView):
    permission_classes = (AllowAny,)
    renderer_classes = (JSONRenderer,)

    @swagger_auto_schema(
        operation_summary="Channel Name",
        operation_description="Public API",
        responses={'200': Serializer})
    @transaction.atomic
    @method_decorator(ensure_csrf_cookie)
    def get(self, request, channel, *args, **kwargs):
        channel_name = None
        for in_service_channel, in_service_channel_name in CHANNEL:
            if in_service_channel == channel:
                channel_name = in_service_channel_name

        return api.response_json(channel_name, status.HTTP_200_OK)


class NowPlayingAPI(RetrieveAPIView):
    permission_classes = (AllowAny,)
    renderer_classes = (JSONRenderer,)

    @swagger_auto_schema(
        operation_summary="Now Playing",
        operation_description="Public API",
        responses={'200': PlayQueueSerializer})
    @transaction.atomic
    @method_decorator(ensure_csrf_cookie)
    def get(self, request, channel, *args, **kwargs):
        redis_data = get_redis_data(channel)
        if redis_data:
            now_playing = redis_data["now_playing"]
            return api.response_json(now_playing, status.HTTP_200_OK)

        return api.response_json(None, status.HTTP_200_OK)


class PlayQueueResetAPI(RetrieveAPIView):
    permission_classes = (IsAdminUser,)
    renderer_classes = (JSONRenderer,)

    @swagger_auto_schema(
        operation_summary="Reset PlayQueue",
        operation_description="Admin Only API",
        responses={'202': PlayQueueSerializer})
    @transaction.atomic
    @method_decorator(ensure_csrf_cookie)
    def get(self, request, channel, *args, **kwargs):
        if channel not in SERVICE_CHANNEL:
            raise ValidationError(_("Invalid service channel"))

        random_tracks = get_random_track(channel, NUM_SAMPLES)

        response_daemon_data = []
        for track in random_tracks:
            location = track.location
            artist = track.artist
            title = track.title

            is_pending_remove = get_is_pending_remove(track.id)
            if is_pending_remove:
                continue
            else:
                response_daemon_data.append({
                    "id": track.id,
                    "location": "/srv/media/%s" % location,
                    "artist": artist,
                    "title": title
                })

        response_daemon = {
            "host": "server",
            "target": channel,
            "command": "setlist",
            "data": response_daemon_data
        }

        api.request_async_threaded("POST", settings.MUSICDAEMON_URL, callback=None, data=response_daemon)

        return api.response_json(response_daemon, status.HTTP_202_ACCEPTED)


class QueueINAPI(RetrieveAPIView):
    permission_classes = (IsAdminUser,)
    renderer_classes = (JSONRenderer,)

    @swagger_auto_schema(
        operation_summary="Add Music to PlayQueue",
        operation_description="Admin Only API",
        responses={'201': "OK"})
    @transaction.atomic
    @method_decorator(ensure_csrf_cookie)
    def get(self, request, channel, track_id, index, *args, **kwargs):
        if channel not in SERVICE_CHANNEL:
            raise ValidationError(_("Invalid service channel"))

        try:
            track = Track.objects.get(id=track_id)
        except Track.DoesNotExist:
            raise ValidationError(_("Music does not exist"))

        is_pending_remove = get_is_pending_remove(track_id)
        if is_pending_remove:
            raise ValidationError(_("You cannot queue-in because the track is reserved pending remove"))

        redis_data = get_redis_data(channel)
        playlist = redis_data["playlist"]

        new_track = {
            "id": track.id,
            "location": "/srv/media/%s" % track.location,
            "artist": track.artist,
            "title": track.title
        }

        playlist.insert(int(index), new_track)
        set_redis_data(channel, "playlist", playlist)

        api.request_async_threaded("POST", settings.MUSICDAEMON_URL, callback=None, data={
            "host": "server",
            "target": channel,
            "command": "setlist",
            "data": playlist
        })

        return api.response_json("OK", status.HTTP_201_CREATED)


class QueueMoveAPI(RetrieveAPIView):
    permission_classes = (IsAdminUser,)
    renderer_classes = (JSONRenderer,)

    @swagger_auto_schema(
        operation_summary="Move Music from PlayQueue",
        operation_description="Admin Only API",
        responses={'201': "OK"})
    @transaction.atomic
    @method_decorator(ensure_csrf_cookie)
    def get(self, request, channel, from_index, to_index, *args, **kwargs):
        if channel not in SERVICE_CHANNEL:
            raise ValidationError(_("Invalid service channel"))

        redis_data = get_redis_data(channel)
        playlist = redis_data["playlist"]

        playlist.insert(to_index, playlist.pop(from_index))
        set_redis_data(channel, "playlist", playlist)

        api.request_async_threaded("POST", settings.MUSICDAEMON_URL, callback=None, data={
            "host": "server",
            "target": channel,
            "command": "setlist",
            "data": playlist
        })

        return api.response_json("OK", status.HTTP_201_CREATED)


class QueueOUTAPI(DestroyAPIView):
    permission_classes = (IsAdminUser,)
    renderer_classes = (JSONRenderer,)

    @swagger_auto_schema(
        operation_summary="Delete Music from PlayQueue",
        operation_description="Admin Only API",
        responses={'202': "OK"})
    @transaction.atomic
    @method_decorator(ensure_csrf_cookie)
    def delete(self, request, channel, index, *args, **kwargs):
        if channel not in SERVICE_CHANNEL:
            raise ValidationError(_("Invalid service channel"))

        redis_data = get_redis_data(channel)
        playlist = redis_data["playlist"]

        playlist.pop(index)
        set_redis_data(channel, "playlist", playlist)

        api.request_async_threaded("POST", settings.MUSICDAEMON_URL, callback=None, data={
            "host": "server",
            "target": channel,
            "command": "unqueue",
            "data": {
                "index_at": index
            }
        })

        return api.response_json("OK", status.HTTP_202_ACCEPTED)


class CallbackOnStartupAPI(RetrieveAPIView):
    permission_classes = (AllowAny,)
    renderer_classes = (JSONRenderer,)

    @swagger_auto_schema(
        operation_summary="Callback on_startup",
        operation_description="Public API",
        responses={'200': PlayQueueSerializer})
    @transaction.atomic
    @method_decorator(ensure_csrf_cookie)
    def get(self, request, channel, *args, **kwargs):
        if channel not in SERVICE_CHANNEL:
            raise ValidationError(_("Invalid service channel"))

        redis_data = get_redis_data(channel)

        response = []
        if redis_data and redis_data["playlist"]:
            # Use pre exist queue
            response = redis_data["playlist"]
        else:
            # Select random track except for last played in 3 hours
            queue_tracks = get_random_track(channel, NUM_SAMPLES)

            # Set playlist
            for track in queue_tracks:
                response.append({
                    "id": int(track.id),
                    "location": "/srv/media/%s" % track.location,
                    "artist": track.artist,
                    "title": track.title
                })

            set_redis_data(channel, "playlist", response)

        return api.response_json_payload(response, status.HTTP_200_OK)


class CallbackOnPlayAPI(CreateAPIView):
    permission_classes = (AllowAny,)
    renderer_classes = (JSONRenderer,)
    serializer_class = PlayQueueSerializer

    @swagger_auto_schema(
        operation_summary="Callback on_play",
        operation_description="Public API",
        responses={'200': "OK"})
    @transaction.atomic
    @method_decorator(ensure_csrf_cookie)
    def post(self, request, channel, *args, **kwargs):
        if channel not in SERVICE_CHANNEL:
            raise ValidationError(_("Invalid service channel"))

        try:
            track = Track.objects.get(id=request.data["id"])
        except Track.DoesNotExist:
            raise ValidationError(_("Music does not exist"))

        history = PlayHistorySerializer(data={
            "track_id": request.data["id"],
            "artist": request.data["artist"],
            "title": request.data["title"],
            "channel": channel,
            "played_at": now()
        })
        history.is_valid(raise_exception=True)
        history.save()

        track.last_played_at = now()
        track.play_count += 1
        track.save()

        return api.response_json("OK", status.HTTP_200_OK)


class CallbackOnStopAPI(CreateAPIView):
    permission_classes = (AllowAny,)
    renderer_classes = (JSONRenderer,)
    serializer_class = PlayQueueSerializer

    @swagger_auto_schema(
        operation_summary="Callback on_stop",
        operation_description="Public API",
        responses={'200': PlayQueueSerializer})
    @transaction.atomic
    @method_decorator(ensure_csrf_cookie)
    def post(self, request, channel, *args, **kwargs):
        if channel not in SERVICE_CHANNEL:
            raise ValidationError(_("Invalid service channel"))

        remove_pending_track()

        random_tracks = get_random_track(channel, 1)

        if random_tracks:
            # Add next track to queue at last
            next_track = random_tracks[0]

            new_track = {
                "id": int(next_track.id),
                "location": "/srv/media/%s" % next_track.location,
                "artist": next_track.artist,
                "title": next_track.title
            }

            redis_data = get_redis_data(channel)
            playlist = redis_data["playlist"]
            playlist.append(new_track)
            set_redis_data(channel, "playlist", playlist)

            return api.response_json_payload(new_track, status.HTTP_200_OK)
        else:
            return api.response_json_payload(None, status.HTTP_200_OK)
