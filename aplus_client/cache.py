from cachetools import TTLCache
from urllib.parse import quote_plus as quote, unquote_plus as unquote
from os import makedirs
from os.path import join, exists, getmtime
from json import dump as json_dump, load as json_load
from time import time


class InMemoryCache(TTLCache):
    def __init__(self, **kwargs):
        kwargs.setdefault('maxsize', 100)
        kwargs.setdefault('ttl', 60)
        super().__init__(**kwargs)


class FilesystemCache(TTLCache):
    _ext = '.json'

    def __init__(self, cache_dir, **kwargs):
        kwargs.setdefault('maxsize', 100)
        kwargs.setdefault('ttl', 3600)
        super().__init__(**kwargs)

        self.cache_dir = cache_dir
        if not exists(cache_dir):
            makedirs(cache_dir)

    def _fn(self, url):
        fn = quote(url) + self._ext
        return join(self.cache_dir, fn)

    def _exists(self, fn):
        return (
            exists(fn) and
            time() < getmtime(fn) + self.ttl
        )

    def __missing__(self, url):
        self._found = False
        fn = self._fn(url)
        if self._exists(fn):
            with open(self._fn(url)) as f:
                data = json_load(f)
            super().__setitem__(url, data)
            return data
        raise KeyError(url)

    def __contains__(self, url):
        if super().__contains__(url):
            return True
        return self._exists(self._fn(url))

    def __setitem__(self, url, data):
        super().__setitem__(url, data)
        with open(self._fn(url), 'w') as f:
            json_dump(data, f)

    # TTLCache uses `del self[key]` and we do not wan't to remove file on maxsize
    #def __delitem__(self, url):
    #    super().__delitem__(url)
    #    raise NotImplementedError

    def __iter__(self):
        raise NotImplementedError

    def __len__(self):
        raise NotImplementedError

    def clear(self):
        raise NotImplementedError
