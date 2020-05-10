from django.urls import path
from radio import views


app_name = 'radio'

urlpatterns = [
    path('list', views.TrackListAPI.as_view()),
    path('track/<int:track_id>', views.TrackAPI.as_view()),
    path('like/<int:track_id>', views.LikeAPI.as_view()),
    path('channelname/<str:channel>', views.ChannelNameAPI.as_view()),
    path('playqueue', views.PlayQueueAPI.as_view()),
    path('playqueue/nowplaying/<str:channel>', views.NowPlayingAPI.as_view()),
    path('playqueue/reset/<str:channel>', views.PlayQueueResetAPI.as_view()),
    path('playqueue/in/<str:channel>/<int:track_id>/<int:index>', views.QueueINAPI.as_view()),
    path('playqueue/move/<str:channel>/<int:from_index>/<int:to_index>', views.QueueMoveAPI.as_view()),
    path('playqueue/out/<str:channel>/<int:index>', views.QueueOUTAPI.as_view()),
    path('callback/on_startup/<str:channel>', views.CallbackOnStartupAPI.as_view()),
    path('callback/on_play/<str:channel>', views.CallbackOnPlayAPI.as_view()),
    path('callback/on_stop/<str:channel>', views.CallbackOnStopAPI.as_view()),
]
