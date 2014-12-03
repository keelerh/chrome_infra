# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import calendar
from datetime import datetime
import hashlib
import json
import logging

from google.appengine.api import memcache
from google.appengine.api import users

from shared.config import VALID_EMAIL_RE

compressed_separators = (',', ':')
minutes_per_day = 24 * 60

def cronjob(cronjob_handler): # pragma: no cover
  def checked_cronjob_handler(self, *args):
    assert (self.request.headers.get('X-AppEngine-Cron') or
        users.is_current_user_admin())
    cronjob_handler(self, *args)
  return checked_cronjob_handler

def cross_origin_json(handler): # pragma: no cover
  def headered_json_handler(self, *args):
    self.response.headers.add_header("Access-Control-Allow-Origin", "*")
    result = handler(self, *args)
    if result:
      self.response.headers.add_header('Content-Type', 'application/json')
      self.response.write(compressed_json_dumps(result))
  return headered_json_handler

def filter_dict(d, keys): # pragma: no cover
  return {key: d[key] for key in d if key in keys}

def has_end_timestamp(**kwargs): # pragma: no cover
  end = kwargs.get('end')
  return end and end < datetime.utcnow()

def is_valid_user(): # pragma: no cover
  if users.is_current_user_admin():
    return True
  user = users.get_current_user()
  return user and VALID_EMAIL_RE.match(user.email())

def memcachize(use_cache_check=None): # pragma: no cover
  def decorator(f):
    def memcachized(**kwargs):
      if use_cache_check and not use_cache_check(**kwargs):
        return f(**kwargs)
      key = '%s.%s(%s)' % (
        f.__module__,
        f.__name__,
        ', '.join('%s=%r' % i for i in sorted(kwargs.items())),
      )
      result = memcache.get(key)
      if result == None:
        result = f(**kwargs)
        if result != None:
          memcache.add(key, result)
      else:
        logging.debug('Memcache hit: ' + key)
      return result
    return memcachized
  return decorator

def password_sha1(password): # pragma: no cover
  return hashlib.sha1(password).hexdigest()

def to_unix_timestamp(dt): # pragma: no cover
  return calendar.timegm(dt.timetuple()) + dt.microsecond / 1e6

def compressed_json_dumps(value): # pragma: no cover
  return json.dumps(value, separators=compressed_separators)