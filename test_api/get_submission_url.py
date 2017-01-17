#!/usr/bin/env python3

import sys
from urllib.parse import urlencode

if __name__ == '__main__':
    try:
        id_ = int(sys.argv[1])
    except:
        id_ = 1
    print(urlencode({'submission_url': 'http://testserver.testserver/api/v2/submissions/%d/grading' % (id_,)}))
