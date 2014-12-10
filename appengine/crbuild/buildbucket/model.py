# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import random

from google.appengine.ext import ndb
from google.appengine.ext.ndb import msgprop
from protorpc import messages


class BuildStatus(messages.Enum):
  SCHEDULED = 1
  BUILDING = 2
  SUCCESS = 3
  FAILURE = 4
  EXCEPTION = 5  # Infrastructure failure.


LEASABLE_STATUSES = (BuildStatus.SCHEDULED, BuildStatus.BUILDING)
FINAL_STATUSES = (BuildStatus.SUCCESS, BuildStatus.FAILURE,
                  BuildStatus.EXCEPTION)


class Callback(ndb.Model):
  """Parameters for a callack push task."""
  url = ndb.StringProperty(required=True, indexed=False)
  headers = ndb.JsonProperty()
  method = ndb.StringProperty(indexed=False)
  queue_name = ndb.StringProperty(indexed=False)


class Build(ndb.Model):
  """Describes a build.

  Build key:
    Build keys are autogenerated integers. Has no parent.

  Attributes:
    owner (string): opaque indexed optional string that identifies the owner of
      the build. For example, this might be a buildset or Gerrit revision.
    namespace (string): a generic way to distinguish builds. Different build
      namespaces have different permissions.
    properties (dict): arbitrary build properties.
    status (BuildStatus): status of the build.
    url (str): a URL to a build-system-specific build, viewable by a human.
    available_since (datetime): the earliest time the build can be leased.
      The moment the build is leased, |available_since| is set to
      (utcnow + lease_duration). On build creation, is set to utcnow.
    lease_key (int): a random value, changes every time a build is leased.
      Can be used to verify that a client is the leaseholder.
    callback_url (str): callback URL to create a push task when build status
      changes.
  """

  owner = ndb.StringProperty()
  namespace = ndb.StringProperty(required=True)
  properties = ndb.JsonProperty()
  status = msgprop.EnumProperty(BuildStatus, default=BuildStatus.SCHEDULED)
  url = ndb.StringProperty(indexed=False)
  available_since = ndb.DateTimeProperty(required=True, auto_now_add=True)
  lease_key = ndb.IntegerProperty(indexed=False)
  callback = ndb.StructuredProperty(Callback, indexed=False)

  def is_available(self):
    return self.available_since <= datetime.datetime.utcnow()

  def is_leasable(self):
    return self.is_available() and self.status in LEASABLE_STATUSES

  def is_status_final(self):
    return self.status in FINAL_STATUSES

  def regenerate_lease_key(self):
    """Changes lease key to a different random integer."""
    while True:
      new_key = random.randint(0, 1 << 31)
      if new_key != self.lease_key:  # pragma: no branch
        self.lease_key = new_key
        break