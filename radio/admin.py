from django.contrib import admin
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.messages import ERROR
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.utils.html import format_html
from django.utils.translation import ugettext_lazy as _
from django.urls import reverse, re_path
from django.utils.safestring import mark_safe
from django_utils.input_filter import InputFilter
from rest_framework.exceptions import ValidationError
from rangefilter.filter import DateRangeFilter, DateTimeRangeFilter
from admin_numeric_filter.admin import RangeNumericFilter
from django.contrib.admin.filters import SimpleListFilter
from .models import Track, PlayHistory, CHANNEL
from .forms import UploadTrackForm, UpdateTrackForm
from .util import get_redis_data, set_redis_data, delete_track, get_random_track, get_is_pending_remove, NUM_SAMPLES
from .uploadhandler import ProgressBarUploadHandler
from django_utils import api


class ScaleFilter(InputFilter):
    parameter_name = 'scale'
    title = _('Scale')

    def queryset(self, request, queryset):
        if self.value() is not None:
            scale = self.value()
            return queryset.filter(
                Q(scale__icontains=scale)
            )


class ChannelFilter(admin.SimpleListFilter):
    template = 'admin/dropdown_filter.html'

    parameter_name = 'channel'
    title = _('Service Channel')

    def lookups(self, request, model_admin):
        return CHANNEL

    def queryset(self, request, queryset):
        if self.value() is not None:
            channel = [self.value()]
            return queryset.filter(
                Q(channel__contains=channel)
            )


class PlayedFilter(SimpleListFilter):
    title = 'Played'
    parameter_name = 'last_played_at'

    def lookups(self, request, model_admin):
        return (
            ('1', _('Played'),),
            ('0', _('Unplayed'),),
        )

    def queryset(self, request, queryset):
        kwargs = {
            '%s' % self.parameter_name: None,
        }
        if self.value() == '0':
            return queryset.filter(**kwargs)
        if self.value() == '1':
            return queryset.exclude(**kwargs)
        return queryset


@admin.register(Track)
class TrackAdmin(admin.ModelAdmin):
    change_list_template = "radio/track_list.html"

    add_form = UploadTrackForm
    change_form = UpdateTrackForm

    add_form_template = "radio/change_form.html"

    list_display = (
        'id', 'user_link',
        'format', 'is_service',
        'channel', 'artist', 'title',
        'bpm', 'scale',
        'duration_field',
        'play_count',
        'queue_in_playlist',
        'uploaded_at', 'updated_at', 'last_played_at',
    )
    search_fields = (
        'title', 'artist', 'bpm', 'scale', 'user__email'
    )
    list_filter = (
        ChannelFilter, ('play_count', RangeNumericFilter),
        ('bpm', RangeNumericFilter), ScaleFilter,
        PlayedFilter, ('last_played_at', DateTimeRangeFilter),
        ('uploaded_at', DateTimeRangeFilter), ('updated_at', DateTimeRangeFilter),
    )
    ordering = ('-id',)

    def user_link(self, obj):
        User = get_user_model()
        user = User.objects.get(email=obj.user.email)
        url = reverse("admin:accounts_user_change", args=[user.id])
        link = '<a href="%s">%s</a>' % (url, obj.user.email)
        return mark_safe(link)
    user_link.short_description = 'User'

    def duration_field(self, obj):
        return obj.duration.strftime("%H:%M:%S.%f")
    duration_field.admin_order_field = 'duration'
    duration_field.short_description = 'Duration'

    def has_change_permission(self, request, obj=None):
        if obj is not None:
            return not get_is_pending_remove(obj.pk)
        else:
            return super().has_change_permission(request, obj=obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None:
            return not get_is_pending_remove(obj.pk)
        else:
            return super().has_delete_permission(request, obj=obj)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['channels'] = CHANNEL
        extra_context['editable'] = True
        extra_context['http_protocol'] = settings.HTTP_PROTOCOL
        extra_context['domain_url'] = settings.DOMAIN_URL
        return super().changelist_view(request, extra_context=extra_context)

    def get_form(self, request, obj=None, **kwargs):
        if not obj:
            self.form = self.add_form
            request.upload_handler = [ProgressBarUploadHandler(request)]
        else:
            self.form = self.change_form
        self.form.user = request.user

        return super().get_form(request, obj, **kwargs)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            re_path(
                r'^(?P<track_id>.+)/(?P<channel>.+)/(?P<index>.+)/queuein$',
                self.admin_site.admin_view(self.process_queuein),
                name='track-queuein',
            ),
            re_path(
                r'^(?P<channel>.+)/(?P<index>.+)/queueout$',
                self.admin_site.admin_view(self.process_queueout),
                name='track-queueout',
            ),
            re_path(
                r'^(?P<channel>.+)/reset',
                self.admin_site.admin_view(self.process_reset),
                name='track-reset',
            ),
        ]
        return custom_urls + urls

    def process_queuein(self, request, track_id, channel, *args, **kwargs):
        if get_is_pending_remove(track_id):
            self.message_user(request, 'You cannot queue-in because the track is reserved pending remove', level=ERROR)
        else:
            redis_data = get_redis_data(channel)
            if not redis_data:
                self.message_user(request, 'Channel does not exist', level=ERROR)
            else:
                playlist = redis_data["playlist"]

                track = Track.objects.get(id=track_id)

                new_track = {
                    "id": track.id,
                    "location": "/srv/media/%s" % track.location,
                    "artist": track.artist,
                    "title": track.title
                }

                playlist.append(new_track)
                set_redis_data(channel, "playlist", playlist)

                api.request_async_threaded("POST", settings.MUSICDAEMON_URL, callback=None, data={
                    "host": "server",
                    "target": channel,
                    "command": "setlist",
                    "data": playlist
                })

                self.message_user(request, 'Success')

        url = reverse(
            'admin:radio_track_changelist',
            current_app=self.admin_site.name,
        )
        return HttpResponseRedirect(url)

    def process_queueout(self, request, channel, index, *args, **kwargs):
        redis_data = get_redis_data(channel)
        if not redis_data:
            self.message_user(request, 'Channel does not exist', level=ERROR)
        else:
            playlist = redis_data["playlist"]

            playlist.pop(int(index))

            set_redis_data(channel, "playlist", playlist)
            api.request_async_threaded("POST", settings.MUSICDAEMON_URL, callback=None, data={
                "host": "server",
                "target": channel,
                "command": "setlist",
                "data": playlist
            })

            self.message_user(request, 'Success')

        url = reverse(
            'admin:radio_track_changelist',
            current_app=self.admin_site.name,
        )
        return HttpResponseRedirect(url)

    def process_reset(self, request, channel, *args, **kwargs):
        redis_data = get_redis_data(channel)
        if not redis_data:
            self.message_user(request, 'Channel does not exist', level=ERROR)
        else:
            random_tracks = get_random_track(channel, NUM_SAMPLES)

            response_daemon_data = []
            for track in random_tracks:
                location = track.location
                artist = track.artist
                title = track.title

                is_pending_remove = get_is_pending_remove(track.id)
                if not is_pending_remove:
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

            self.message_user(request, 'Success')

        url = reverse(
            'admin:radio_track_changelist',
            current_app=self.admin_site.name,
        )
        return HttpResponseRedirect(url)

    def queue_in_playlist(self, obj):
        html = ''
        args = []
        for in_service_channel, in_service_channel_name in CHANNEL:
            is_pending_remove = get_is_pending_remove(obj.pk)
            if not is_pending_remove:
                html += '<a class="button" href="{}">%s</a>&nbsp;' % in_service_channel_name
                args.append(
                    reverse('admin:track-queuein', args=[obj.pk, in_service_channel, -1]),
                )
        return format_html(html, *args)
    queue_in_playlist.short_description = 'Queue In'
    queue_in_playlist.allow_tags = True

    def delete_queryset(self, request, queryset):
        print('========================delete_queryset========================')
        print(queryset)

        """
        you can do anything here BEFORE deleting the object(s)
        """

        try:
            for track in queryset:
                delete_track(track)
        except ValidationError as e:
            self.message_user(request, e.detail, level=ERROR)
        else:
            self.message_user(request, "Success")

        """
        you can do anything here AFTER deleting the object(s)
        """

        print('========================delete_queryset========================')

    def delete_model(self, request, obj):
        print('============================delete_model============================')
        print(obj)

        """
        you can do anything here BEFORE deleting the object
        """

        try:
            delete_track(obj)
        except ValidationError as e:
            self.message_user(request, e.detail, level=ERROR)
        else:
            self.message_user(request, "Success")

        """
        you can do anything here AFTER deleting the object
        """

        print('============================delete_model============================')


class TrackInline(admin.StackedInline):
    model = Track
    can_delete = False


@admin.register(PlayHistory)
class PlayHistoryAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'channel', 'artist', 'title', 'played_at',
    )
    search_fields = (
        'artist', 'title'
    )
    list_filter = (
        ChannelFilter,
    )
    ordering = ('-played_at',)

    def track_link(self, obj):
        track = Track.objects.get(id=obj.track.id)
        url = reverse("admin:radio_track_change", args=[track.id])
        link = '<a href="%s">%s</a>' % (url, obj.track.id)
        return mark_safe(link)
    track_link.short_description = 'Track'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
