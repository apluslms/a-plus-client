from .client import AplusGraderClient


class AplusGraderMixin:
    """
    Django view mixin that defines grading_data if submission_url is found
    from query parameters
    """
    grading_data = None

    def get_aplus_client(self, request, required=False):
        submission_url = request.GET.get('submission_url', None)
        if submission_url:
            aplus_client = AplusGraderClient(submission_url)
            self.grading_data = aplus_client.grading_data
        elif required:
            return HttpResponseBadRequest("Missing submission_url query parameter")

    def get(self, request, *args, **kwargs):
        fail = self.get_aplus_client(request)
        if fail:
            return fail
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        fail = self.get_aplus_client(request, required=True)
        if fail:
            return fail
        return super().post(request, *args, **kwargs)
