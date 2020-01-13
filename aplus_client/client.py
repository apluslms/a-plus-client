import requests
import logging
from cgi import parse_header
from os.path import isfile
from urllib.parse import parse_qsl as urlparse_qsl, urlencode, urlsplit, urlunsplit

from .cache import InMemoryCache
from .debugging import AplusClientDebugging, FakeResponse
from .util import urlsplit_clean


NoDefault = object()

logger = logging.getLogger('aplus_client.client')


class ConnectionErrorResponse(FakeResponse):
    """
    Represents ConnectionError exception as fake response object
    We use error code 504 'Gateway Timeout'
    """
    def __init__(self, error, url):
        self.error = error
        logger.critical("%s when requesting url '%s': %s", error.__class__.__name__, url, error)
        reason = '%s: %s' % (error.__class__.__name__, error)
        super().__init__(url, 504, reason)


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
            if data:
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

    def __iter__(self):
        return iter(self._data)

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
        data = self.find_first(data)
        self.add_data(data)

    @staticmethod
    def find_first(data):
        previous = data['previous']
        if previous is not None:
            data = self._client._load_cached_data(previous)
            previous = data['previous']
        return data

    @staticmethod
    def is_paginated(data, source_url=None):
        return (source_url
                and len(data) == 4
                and frozenset(data.keys()) == frozenset(('count', 'next', 'previous', 'results'))
                and isinstance(data['results'], list))

    def __iter__(self):
        yield from self._data
        while True:
            at = len(self._data)
            if not self.load_next():
                break
            yield from self._data[at:]

    def load_next(self):
        if self._next:
            data = self._client._load_cached_data(self._next)
            self.add_data(data)
            return True
        return False

    def add_data(self, data):
        if isinstance(data, dict):
            self._count = data['count']
            self._next = data['next']
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



class AplusClientMetaclass(type):
    def __call__(cls, *args, **kwargs):
        debug = kwargs.pop('debug_enabled', False)
        if debug:
            cls = type(cls.__name__ + 'Debuging', (AplusClientDebugging, cls), {})
        return type.__call__(cls, *args, **kwargs)


class AplusClient(metaclass=AplusClientMetaclass):
    """
    Base class for A-Plus API client.
    Handles get/post requests and converting responses to AplusApiObjects
    """
    def __init__(self, version=None, cache=None):
        self.api_version = version
        self.base_url = None
        self.session = requests.session()
        self.__params = {}
        self._cache = InMemoryCache() if cache is None else cache

    @staticmethod
    def api_base_url(url):
        url = urlsplit_clean(url)
        basepath = '/'.join(url.path.split('/', 3)[:3]) # only: /api/vN/
        url = url._replace(path=basepath, query='', fragment='')
        return url.geturl()

    def set_base_url_from(self, url):
        self.base_url = self.api_base_url(url)

    @staticmethod
    def normalize_url(url):
        url = urlsplit_clean(url)
        params = urlparse_qsl(url.query)
        url = url._replace(query='', fragment='')
        return url.geturl(), params

    @staticmethod
    def join_params(url, params):
        return urlsplit(url)._replace(query=urlencode(params)).geturl()

    def _get_full_url(self, url):
        if url[0] == '/':
            if not self.base_url:
                raise RuntimeError("APIClient doesn't support partial urls without base url")
            url = self.base_url + url
        return url

    def get_headers(self):
        accept = 'application/vnd.aplus+json'
        if self.api_version:
            accept += '; version=%s' % (self.api_version,)
        return {'Accept': accept}

    def update_params(self, params):
        self.__params.update(params)

    def get_params(self):
        return self.__params

    def do_get(self, url, **kwargs):
        url = self._get_full_url(url)
        kwargs['headers'] = self.get_headers()
        kwargs['params'] = self.get_params()
        kwargs.setdefault('timeout', (3.2, 9.6))
        logger.debug("making GET '%s', %s", url, kwargs)

        try:
            return self.session.get(url, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as err:
            return ConnectionErrorResponse(err, url)

    def do_post(self, url, data=None, json=None, timeout=None):
        assert data or json, 'You must specify either data or json'
        url = self._get_full_url(url)
        headers = self.get_headers()
        params = self.get_params()
        if not timeout:
            timeout = (3.2, 9.6)
        logger.debug("making POST '%s', headers=%r, params=%r, data=%r, json=%r", url, headers, params, data, json)
        try:
            return self.session.post(url, headers=headers, data=data, json=json, params=params, timeout=timeout)
        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as err:
            return ConnectionErrorResponse(err, url)

    def _load_json_data(self, url):
        resp = self.do_get(url)
        if resp.status_code != 200:
            logger.info("Got status %d from url %s", resp.status_code, url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        return resp.json()

    def _load_cached_data(self, url, skip_cache=False):
        try:
            if skip_cache:
                raise KeyError
            data = self._cache[url]
        except KeyError:
            try:
                data = self._load_json_data(url)
            except ValueError:
                data = None
            else:
                self._cache[url] = data
        else:
            logger.debug("cache hit for %r", url)
        return data

    def load_data(self, url, skip_cache=False):
        url = self._get_full_url(url)
        data = self._load_cached_data(url, skip_cache=skip_cache)
        return AplusApiObject._wrap(client=self, data=data, source_url=url)

    def load_file(self, filename, url):
        # TODO: if-modified-sinze, cache and force support
        if not isfile(filename):
            url = self._get_full_url(url)
            resp = self.do_get(url, stream=True)
            if resp.status_code != 200:
                return None
            with open(filename, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
            header_cd = resp.headers.get('Content-Disposition')
            if header_cd:
                value, params = parse_header(header_cd)
                if value == 'attachment' and 'filename' in params:
                    filename = params['filename']
        return filename


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
        url, params = self.normalize_url(submission_url)
        self.grading_url = url
        self.update_params(params)

    @property
    def grading_data(self):
        data = self.load_data(self.grading_url)
        self.__dict__['grading_data'] = data
        return data

    def grade(self, data, **kwargs):
        return self.do_post(self.grading_url, data, **kwargs)
