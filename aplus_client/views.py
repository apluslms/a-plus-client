from .client import AplusGraderClient


class Grading:
    def __init__(self, data):
        self.__d = data

    @property
    def form_spec(self):
        return self.__d.exercise.exercise_info.get_item('form_spec')

    @property
    def submitters(self):
        return self.__d.submission.submitters


class AplusGraderMixin:
    """
    Django view mixin that defines grading_data if submission_url is found
    from query parameters
    """
    grading_data = None

    def get_aplus_client(self, request, required=False):
        self.submission_url = submission_url = request.GET.get('submission_url', None)
        self.post_url = request.GET.get('post_url', None)
        if submission_url:
            self.aplus_client = AplusGraderClient(submission_url)
        elif required:
            return HttpResponseBadRequest("Missing submission_url query parameter")

    @property
    def grading_data(self):
        return Grading(self.aplus_client.grading_data)

    def get(self, request, *args, **kwargs):
        fail = self.get_aplus_client(request)
        return fail if fail else super().post(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        fail = self.get_aplus_client(request, required=True)
        return fail if fail else super().post(request, *args, **kwargs)
