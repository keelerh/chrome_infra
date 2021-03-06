# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import logging

from google.appengine.api import urlfetch

from common.retry_http_client import RetryHttpClient


class HttpClientAppengine(RetryHttpClient):  # pragma: no cover
  """A http client for running on appengine."""

  def _Get(self, url, timeout, headers=None):
    # We wanted to validate certificate to avoid the man in the middle.
    if not headers:
      headers = {}
    result = urlfetch.fetch(
        url, headers=headers, deadline=timeout, validate_certificate=True)

    if (result.status_code != 200 and
        (not self.no_error_logging_statuses or
         result.status_code not in self.no_error_logging_statuses)):
      logging.error('Request to %s resulted in %d, headers:%s', url,
                    result.status_code, json.dumps(result.headers.items()))

    return result.status_code, result.content
