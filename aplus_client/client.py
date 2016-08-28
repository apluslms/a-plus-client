import requests
import json
import logging
from urllib.parse import urlsplit, urlunsplit, parse_qsl as urlparse_qsl
from cachetools import TTLCache
from collections import namedtuple


TEST_URL_PREFIX = "http://testserver/api/v2/"
TEST_DATA_PATH = "test_api"


NoDefault = object()
FakeResponse = namedtuple('FakeResponse', ('status_code', 'text'))


logger = logging.getLogger('aplus_client.client')


class AplusApiObject:
    """
    Base class for generic A-Plus API objects
    """
    def __init__(self, client, data=None, source_url=None):
        self._client = client
        self._source_url = source_url
        if data:
            self.add_data(data)

    @staticmethod
    def _wrap(client, data, source_url=None):
        if isinstance(data, dict):
            if AplusApiPaginated.is_paginated(data, source_url):
                cls = AplusApiPaginated
            elif AplusApiError.is_error(data):
                cls = AplusApiError
            else:
                cls = AplusApiDict
        elif isinstance(data, list):
            cls = AplusApiList
        else:
            # we do not decorate anything else than dict and list
            return data

        return cls(client=client, data=data, source_url=source_url)


class AplusApiDict(AplusApiObject):
    """
    Represents dict types returned from A-Plus API
    """
    def __init__(self, *args, **kwargs):
        self._data = {}
        super().__init__(*args, **kwargs)
        self._update_url_prefix()

    def __str__(self):
        return "<{cls}({url})>".format(cls=self.__class__.__name__,
                                       url=self._source_url)

    def __repr__(self):
        return "<{cls}({url}) at 0x{id:x}>".format(
            cls=self.__class__.__name__,
            url=self._source_url or self._full_url,
            id=id(self),
        )

    def _update_url_prefix(self):
        url = self._source_url or self._full_url
        if url:
            url = '/'.join(url.split('/', 4)[:4])
        self._url_prefix = url

    @property
    def _full_url(self):
        return self._data.get('url', None)

    @property
    def is_all_loaded(self):
        return self._source_url and self._source_url == self._full_url

    def add_data(self, data):
        self._data.update(data)

    def load_all(self):
        furl = self._full_url
        if furl and self._source_url != furl:
            data = self._client._load_cached_data(furl)
            self.add_data(data)
            self._source_url = furl
            self._update_url_prefix()
            return True
        return False

    def get_item(self, key, default=NoDefault):
        """
        Finds and returns value from dict with key

        If key is not found from stored data, we try to fully load the object
        and search is repeated.

        In most cases you should use .get() instead to load api urls also
        """
        try:
            return self._data[key]
        except KeyError as err:
            if self.load_all():
                try:
                    return self._data[key]
                except KeyError:
                    pass

            # no value is found
            if default is not NoDefault:
                return default
            raise err

    def get(self, key, default=None):
        """
        Finds and returns value from dict with key

        if the value starts with expected api url it will be loaded and
        converted to aplus dict
        """
        value = self.get_item(key, default=default)
        if (key != 'url' and isinstance(value, str) and
            self._url_prefix and value.startswith(self._url_prefix)):
            try:
                return self._client.load_data(value)
            except: # FIXME: too wide
                print("ERROR: couldn't get json for %s" % (value,))
        return AplusApiObject._wrap(self._client, value)

    def __getitem__(self, key):
        return self.get(key, default=NoDefault)

    def __contains__(self, key):
        try:
            self.get_item(key)
            return True
        except KeyError:
            return False

    def keys(self):
        return self._data.keys()

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError("%s has no attribute '%s'" % (self, key))


class AplusApiList(AplusApiObject):
    """
    Represents list types returned from A-Plus API
    """
    def __init__(self, *args, **kwargs):
        self._data = []
        super().__init__(*args, **kwargs)

    def add_data(self, data):
        for value in data:
            self._data.append(AplusApiObject._wrap(self._client, value))

    def __len__(self):
        return len(self._data)

    def __getitem__(self, idx):
        return self._data[idx]


class AplusApiPaginated(AplusApiList):
    """
    Represents paginated dict types returned from A-Plus API

    Response dict is like:
    {
        "count": 1023
        "next": "https://api.example.org/accounts/?page=5",
        "previous": "https://api.example.org/accounts/?page=3",
        "results": [
            // data elements
        ]
    }
    """
    def __init__(self, data, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._count = data['count']
        self._next = data['next']
        self._previous = data['previous']
        self._first_loaded = bool(self._previous is None)
        self._last_loaded = bool(self._next is None)
        # FIXME: handle multiple pages
        # NOTE: start by finding first page
        self.add_data(data)

    @staticmethod
    def is_paginated(data, source_url=None):
        return (source_url
                and len(data) == 4
                and frozenset(data.keys()) == frozenset(('count', 'next', 'previous', 'results'))
                and isinstance(data['results'], list))

    def add_data(self, data):
        if isinstance(data, dict):
            data = data['results']
        super().add_data(data)

    def __len__(self):
        return self._count


class AplusApiError(AplusApiObject):
    """
    Represents error responses from the A-Plus API
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.message = ''

    @staticmethod
    def is_error(data):
        return (len(data) == 1
                and 'detail' in data
                and isinstance(data['detail'], str))

    def add_data(data):
        self.message = data['detail']


CACHE = TTLCache(maxsize=100, ttl=60)

class AplusClient:
    """
    Base class for A-Plus API client.
    Handles get/post requests and converting responses to AplusApiObjects
    """
    def __init__(self, version=None, debug_enabled=True):
        self.api_version = version
        self.session = requests.session()
        self._debug = debug_enabled

    def get_headers(self):
        accept = 'application/vnd.aplus+json'
        if self.api_version:
            accept += '; version=%s' % (self.api_version,)
        return {'Accept': accept}

    def get_params(self):
        return {}

    def do_get(self, url):
        headers = self.get_headers()
        params = self.get_params()
        logger.critical("making GET '%s', headers=%r, params=%r", url, headers, params)
        return self.session.get(url, headers=headers, params=params)

    def do_post(self, url, data):
        if self._debug and url.startswith(TEST_URL_PREFIX):
            logger.debug("making test POST '%s', data=%r", url, data)
            return FakeResponse(200, 'ok')

        headers = self.get_headers()
        params = self.get_params()
        logger.debug("making POST '%s', headers=%r, params=%r, data=%r", url, headers, params, data)
        return self.session.post(url, headers=headers, data=data, params=params)

    def _load_json_data(self, url):
        if self._debug and url.startswith(TEST_URL_PREFIX):
            furl = url[len(TEST_URL_PREFIX):].strip('/').replace('/', '__')
            fn = ''.join((TEST_DATA_PATH, '/', furl, ".json"))
            logger.debug("making test GET '%s', file=%r", url,fn)
            with open(fn, 'r') as f:
                try:
                    return json.loads(f.read())
                except ValueError as e:
                    raise ValueError("Json error in {}: {}".format(fn, e))
        resp = self.do_get(url)
        # FIXME: if resp.status != 200:
        try:
            return resp.json()
        except ValueError:
            return None

    def _load_cached_data(self, url):
        data = CACHE.get(url, None)
        if data is None:
            data = self._load_json_data(url)
            CACHE[url] = data
        else:
            logger.debug("cache hit for %r", url)
        return data

    def load_data(self, url):
        data = self._load_cached_data(url)
        return AplusApiObject._wrap(client=self, data=data, source_url=url)


class AplusTokenClient(AplusClient):
    """
    Simple extension to A-Plus API client to support token auth
    """
    # TODO: add slumber - http://slumber.readthedocs.io/en/v0.6.0/
    def __init__(self, token, **kwargs):
        super().__init__(**kwargs)
        self.token = token

    def get_headers(self):
        h = super().get_headers()
        h['Authorization'] = 'Token %s' % (self.token,)
        return h


class AplusGraderClient(AplusClient):
    """
    Extension to A-Plus API client to support submssion_url based
    A-Plus grading backends.
    """
    def __init__(self, submission_url, **kwargs):
        super().__init__(**kwargs)
        url = urlsplit(submission_url)
        self.grading_url = urlunsplit(url[:3] + tuple(('', ''))) # drop query so local cache will ignore auth token
        self._params = urlparse_qsl(url.query)

    @property
    def grading_data(self):
        data = self.load_data(self.grading_url)
        self.__dict__['grading_data'] = data
        return data

    def grade(self, data):
        return self.do_post(self.grading_url, data)

    def get_params(self):
        p = super().get_params()
        p.update(self._params)
        return p
