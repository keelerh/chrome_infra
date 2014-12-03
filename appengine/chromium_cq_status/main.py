# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import webapp2

from handlers.admin_dispatch import AdminDispatch
from handlers.index import Index
from handlers.patch_status import PatchStatus
from handlers.post import Post
from handlers.stats_viewer import StatsViewer
from handlers.stats_data_points import StatsDataPoints

handlers = [
  (r'/', Index),
  (r'/admin/(.*)', AdminDispatch),
  (r'/patchset/(.*)/(.*)', PatchStatus),  # Legacy URL for old links.
  (r'/patch-status/(.*)/(.*)', PatchStatus),
  (r'/post', Post),
  (r'/stats/(highest|lowest)/(.*)/(.*)', StatsDataPoints),
  (r'/stats/(.*)/(.*)', StatsViewer),
]

app = webapp2.WSGIApplication(handlers, debug=True)