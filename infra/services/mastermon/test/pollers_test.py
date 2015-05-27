# Copyright (c) 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

import mock

from infra.services.mastermon import pollers


class FakePoller(pollers.Poller):
  endpoint = '/foo'

  def __init__(self, base_url):
    super(FakePoller, self).__init__(base_url)
    self.called_with_data = None

  def handle_response(self, data):
    self.called_with_data = data


@mock.patch('requests.get')
class PollerTest(unittest.TestCase):
  def test_requests_url(self, mock_get):
    response = mock_get.return_value
    response.json.return_value = {'foo': 'bar'}
    response.status_code = 200

    p = FakePoller('http://foobar')
    self.assertTrue(p.poll())

    mock_get.assert_called_once_with('http://foobar/json/foo')

  def test_returns_false_for_non_200(self, mock_get):
    response = mock_get.return_value
    response.status_code = 404

    p = FakePoller('http://foobar')
    self.assertFalse(p.poll())

  def test_calls_handle_response(self, mock_get):
    response = mock_get.return_value
    response.json.return_value = {'foo': 'bar'}
    response.status_code = 200

    p = FakePoller('http://foobar')
    self.assertTrue(p.poll())
    self.assertEqual({'foo': 'bar'}, p.called_with_data)


class ClockPollerTest(unittest.TestCase):
  def test_response(self):
    p = pollers.ClockPoller('')

    p.handle_response({'server_uptime': 123})
    self.assertEqual(123, p.uptime.get())


class BuildStatePollerTest(unittest.TestCase):
  def test_response(self):
    p = pollers.BuildStatePoller('')

    p.handle_response({
      'accepting_builds': True,
      'builders': [
        {
          'builderName': 'foo',
          'currentBuilds': [],
          'pendingBuilds': 4,
          'state': 'offline',
        },
        {
          'builderName': 'bar',
          'currentBuilds': [1, 2, 3],
          'pendingBuilds': 0,
          'state': 'building',
        },
      ]
    })
    self.assertEqual(True, p.accepting_builds.get())
    self.assertEqual(0, p.current_builds.get({'builder': 'foo'}))
    self.assertEqual(4, p.pending_builds.get({'builder': 'foo'}))
    self.assertEqual('offline', p.state.get({'builder': 'foo'}))
    self.assertEqual(3, p.current_builds.get({'builder': 'bar'}))
    self.assertEqual(0, p.pending_builds.get({'builder': 'bar'}))
    self.assertEqual('building', p.state.get({'builder': 'bar'}))


class SlavesPollerTest(unittest.TestCase):
  def test_response(self):
    p = pollers.SlavesPoller('')

    p.handle_response({
      'slave1': {
        'builders': {},
        'connected': True,
        'runningBuilds': [],
      },
      'slave2': {
        'builders': {
          'builder1': {},
          'builder2': {},
        },
        'connected': True,
        'runningBuilds': [1, 2],
      },
      'slave3': {
        'builders': {
          'builder1': {},
        },
        'connected': False,
        'runningBuilds': [],
      },
    })
    self.assertEqual(2, p.total.get({'builder': 'builder1'}))
    self.assertEqual(1, p.total.get({'builder': 'builder2'}))
    self.assertEqual(1, p.connected.get({'builder': 'builder1'}))
    self.assertEqual(1, p.connected.get({'builder': 'builder2'}))
    self.assertEqual(1, p.running_builds.get({'builder': 'builder1'}))
    self.assertEqual(1, p.running_builds.get({'builder': 'builder2'}))