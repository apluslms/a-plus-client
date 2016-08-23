from urllib.parse import urljoin, urlencode
from django.conf import settings
from django.http import HttpResponseBadRequest

from ..client import (
    TEST_URL_PREFIX,
    AplusGraderClient,
)

TEST_EXC_URL = urljoin(TEST_URL_PREFIX, "exercises/2/grader/")
TEST_SUB_URL = urljoin(TEST_URL_PREFIX, "submissions/2/grader/")

class GradingWrapper:
    def __init__(self, data):
        self.__d = data

    @property
    def exercise(self):
        return self.__d.exercise

    @property
    def course(self):
        return self.__d.exercise.course

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

    def get_aplus_client(self, request):
        submission_url = request.GET.get('submission_url', None)
        post_url = request.GET.get('post_url', None)

        if not submission_url:
            if settings.DEBUG:
                # When we DEBUG mode is on, we use test resource
                is_safe = request.method in ('GET', 'HEAD', 'OPTIONS')
                submission_url = TEST_EXC_URL if is_safe else TEST_SUB_URL
                post_url = request.build_absolute_uri('?' + urlencode([('submission_url', TEST_SUB_URL)]))
            else:
                return HttpResponseBadRequest("Missing required submission_url query parameter")
        elif not post_url and settings.DEBUG:
            post_url = request.build_absolute_uri('?' + urlencode([('submission_url', submission_url)]))

        self.submission_url = submission_url
        self.post_url = post_url
        self.aplus_client = AplusGraderClient(submission_url, debug_enabled=settings.DEBUG)

    @property
    def grading_data(self):
        return GradingWrapper(self.aplus_client.grading_data)

    def get(self, request, *args, **kwargs):
        fail = self.get_aplus_client(request)
        return fail if fail else super().post(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        fail = self.get_aplus_client(request)
        return fail if fail else super().post(request, *args, **kwargs)
