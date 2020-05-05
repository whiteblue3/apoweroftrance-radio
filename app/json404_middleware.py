from django.http import HttpResponse
import json


class JSON404Middleware:
    """
    Returns JSON 404 instead of HTML
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = None
        if not response:
            response = self.get_response(request)
        if hasattr(self, 'process_response'):
            response = self.process_response(request, response)
        return response

    def process_response(self, request, response):
        if response.status_code == 404 and 'application/json' not in response['content-type']:
            data = {'detail': '{0} not found'.format(request.path)}
            # response = HttpResponse(json.dumps(data), content_type='application/json', status=404)
            response.data = json.dumps(data)
            response.content = json.dumps(data)
            response['Content-Type'] = 'application/json'
            response.status_code = 404
        return response
