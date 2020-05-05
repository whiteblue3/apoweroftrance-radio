from django.conf import settings
from django.http import HttpResponseRedirect
from django.utils.deprecation import MiddlewareMixin


class RemoveNextMiddleware(MiddlewareMixin):
    def __init__(self, *args, **kwargs):
        """Constructor method."""
        super().__init__(*args, **kwargs)

    def process_request(self, request):
        next_value = request.GET.get('next')
        if request.path == "/admin/login/" and next_value is not None:
            return HttpResponseRedirect("/admin/login/")
