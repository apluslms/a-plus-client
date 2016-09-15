from functools import wraps
from urllib.parse import urljoin, urlencode
from django.conf import settings
from django.http import HttpResponseBadRequest
from django.utils import translation

from ..client import AplusGraderClient
from ..debugging import TEST_URL_PREFIX


TEST_EXC_URL = urljoin(TEST_URL_PREFIX, "exercises/2/grader/")
TEST_SUB_URL = urljoin(TEST_URL_PREFIX, "submissions/2/grader/")


def none_on_attributeerror(func):
    @wraps(func)
    def wrap(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AttributeError:
            return None
    return wrap


class GradingWrapper:
    def __init__(self, data):
        self.__d = data

    @property
    @none_on_attributeerror
    def exercise(self):
        return self.__d.exercise

    @property
    @none_on_attributeerror
    def course(self):
        return self.__d.exercise.course

    @property
    @none_on_attributeerror
    def language(self):
        return self.__d.exercise.course.language or None

    @property
    @none_on_attributeerror
    def form_spec(self):
        return self.__d.exercise.exercise_info.get_item('form_spec')

    @property
    @none_on_attributeerror
    def submitters(self):
        return self.__d.submission.submitters


def bad_submission_url(url):
    rel = not any((
        url.startswith(s)
        for s in ('http://', 'https://', '//')
    ))
    if rel:
        return True
    url = url.split('//', 1)[1]
    local = any((
        url.startswith(s)
        for s in ('localhost', '127.0.0.1', 'testserver')
    ))
    return local


class AplusGraderMixin:
    """
    Django view mixin that defines grading_data if submission_url is found
    from query parameters
    """
    grading_data = None

    def get_aplus_client(self, request):
        submission_url = request.GET.get('submission_url', None)
        post_url = request.GET.get('post_url', None)
        debug = settings.DEBUG

        if not submission_url:
            if debug:
                # When we DEBUG mode is on, we use test resource
                is_safe = request.method in ('GET', 'HEAD', 'OPTIONS')
                submission_url = TEST_EXC_URL if is_safe else TEST_SUB_URL
                post_url = request.build_absolute_uri('?' + urlencode([('submission_url', TEST_SUB_URL)]))
            else:
                return HttpResponseBadRequest("Missing required submission_url query parameter")
        elif bad_submission_url(submission_url) and not debug:
            return HttpResponseBadRequest("Bad submission_url in query parameter")
        elif not post_url and debug:
            post_url = request.build_absolute_uri('?' + urlencode([('submission_url', submission_url)]))

        self.submission_url = submission_url
        self.post_url = post_url
        self.aplus_client = AplusGraderClient(submission_url, debug_enabled=settings.DEBUG)

        # i18n
        language = self.grading_data.language
        translation.activate(language)

    @property
    def grading_data(self):
        return GradingWrapper(self.aplus_client.grading_data)

    def get(self, request, *args, **kwargs):
        fail = self.get_aplus_client(request)
        return fail if fail else super().post(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        fail = self.get_aplus_client(request)
        return fail if fail else super().post(request, *args, **kwargs)
