"""backend URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import os
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, re_path, include
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from radio.views import upload_progress


admin.site.site_header = "A Power of Trance"
admin.site.site_title = "Welcome to A Power of Trance"
admin.site.index_title = "Radio Admin"


schema_url_patterns = [
    # path('v1/user/', include('accounts.urls', namespace='user')),
    path('v1/radio/', include('radio.urls', namespace='radio')),
]

schema_view = get_schema_view(
    openapi.Info(
        title="A Power of Trance Radio API",
        default_version='v1',
        description="Usage: <br />"
                    "1. user/authenticate to signin <br />"
                    "2. copy token in response <br />"
                    "3. click authenticate at right-top <br />"
                    "4. input like 'Bearer <Token>' and click Authorize <br />"
                    "5. Use other API <br />"
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
    patterns=schema_url_patterns,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    re_path(r'^upload_progress/?', upload_progress, name="upload_progress"),
] + schema_url_patterns + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

if os.environ.get('ENABLE_SWAGGER') == '1':
    urlpatterns += [
        re_path(r'^docs(?P<format>\.json|\.yaml)/$', schema_view.without_ui(cache_timeout=0), name='schema-json'),
        re_path(r'^docs/$', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
        re_path(r'^redoc/$', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    ]
