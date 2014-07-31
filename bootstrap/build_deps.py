#!/usr/bin/env python
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import hashlib
import os
import shutil
import subprocess
import sys

import bootstrap

from util import ROOT, WHEELHOUSE, WHEELS_URL, SOURCE_URL

from util import tempdir, tempname, read_deps, print_deps, platform_tag


DEFAULT_REPO = 'https://chromium.googlesource.com/infra/third_party/{name}'


def has_custom_build(name):
  return os.path.exists(os.path.join(ROOT, 'custom_builds', name + '.py'))


def pip(*args, **kwargs):
  subprocess.check_call(
      (os.path.join(sys.prefix, 'bin', 'pip'),) + args, **kwargs)


def wheel(arg, source_sha, build, build_options):
  with tempdir() as tdir:
    args = ['wheel', '--no-index', '--no-deps', '--wheel-dir', tdir]
    for op in build_options:
      args += ['--global-option', op]
    args += [arg]
    pip(*args)
    grab_wheel(tdir, WHEELHOUSE, source_sha, build)


def grab_wheel(src, dst, source_sha, build):
  # late import lets us grab the virtualenv pip
  from pip.wheel import Wheel

  items = os.listdir(src)
  assert len(items) == 1, 'Wrong number of files in wheel directory: %r' % items

  wheelfile = items[0]
  wheel_info = Wheel.wheel_file_re.match(wheelfile)

  assert wheel_info is not None, 'Not a wheel file? %r' % wheelfile

  plat_tag = ''
  if not wheelfile.endswith('none-any.whl'):
    plat_tag = platform_tag()

  shutil.copyfile(
      os.path.join(src, wheelfile),
      os.path.join(dst, '{}-{}_{}{}{}'.format(
        wheel_info.group('namever'),
        build,
        source_sha,
        plat_tag,
        wheel_info.group(4),
      )))


def run_custom_build(name, link, sha, build):
  from pip.index import Link
  from pip.download import unpack_file_url, unpack_vcs_link, is_vcs_url

  assert has_custom_build(name)

  link = Link(link, trusted=True)
  unpack = unpack_vcs_link if is_vcs_url(link) else unpack_file_url

  with tempdir() as tmpd, tempdir() as wheeld:  # pylint: disable=C0321
    unpack(link, tmpd)
    m = getattr(__import__('custom_builds.%s' % (name,)), name)
    m.Build(tmpd, wheeld)
    grab_wheel(wheeld, WHEELHOUSE, sha, build)


def process_git(name, rev, build, build_options, repo):
  print
  print 'Processing (git)', name, rev

  url = repo.format(name=name) + '@' + rev
  if not url.startswith('git+'):
    url = 'git+' + url

  if not has_custom_build(name):
    wheel(url, rev, build, build_options)
  else:
    run_custom_build(name, url, rev, build)


def process_gs(name, sha_ext, build, build_options):
  print
  print 'Processing (gs)', name, sha_ext

  sha, ext = sha_ext.split('.', 1)
  with tempname(ext) as tmp:
    link = 'file://' + tmp
    subprocess.check_call(['gsutil', 'cp', SOURCE_URL.format(sha_ext), tmp])
    with open(tmp, 'rb') as f:
      assert hashlib.sha1(f.read()).hexdigest() == sha
    if not has_custom_build(name):
      wheel(link, sha, build, build_options)
    else:
      run_custom_build(name, link, sha, build)


def clear_wheelhouse():
  shutil.rmtree(WHEELHOUSE, ignore_errors=True)
  try:
    os.makedirs(WHEELHOUSE)
  except OSError:
    pass


def push_wheelhouse():
  return subprocess.call(['gsutil', '-m', 'cp', WHEELHOUSE + '/*', WHEELS_URL])


def main(args):
  parser = argparse.ArgumentParser()
  parser.add_argument(
      'to_build', nargs='*',
      help='Names of packages to build. Defaults to all packages.')
  opts = parser.parse_args(args)

  if 'Ubuntu' in platform_tag() and ROOT.startswith('/usr/local/'):
    print >> sys.stderr, "\n".join([
      "Due to a bug in Ubuntu's python distribution, build_deps.py does not",
      "work when run from under a path beginning with /usr/local/. Please ",
      "clone to a different path, and try again.",
      "",
      "Bug: https://github.com/pypa/virtualenv/issues/118"
    ])
    return 1

  to_build = set(opts.to_build)

  build_env = os.path.join(ROOT, 'BUILD_ENV')

  print 'Parsing deps.pyl'
  deps = read_deps(os.path.join(ROOT, 'deps.pyl'))
  bootstrap.activate_env(build_env, {'wheel': deps.pop('wheel')})

  print 'Finding missing deps'
  missing_deps = {}
  for name, entry in deps.iteritems():
    if to_build and name not in to_build:
      continue
    try:
      bootstrap.get_links({name: entry})
    except bootstrap.NoWheelException:
      missing_deps[name] = entry

  if not missing_deps:
    print 'Nothing to process'
    return

  print 'Processing deps:'
  print_deps(missing_deps)

  for name, options in missing_deps.iteritems():
    clear_wheelhouse()
    # TODO(iannucci):  skip entries which already exist in gs
    if 'rev' in options:
      process_git(name, options['rev'], options['build'],
                  options.get('build_options', ()),
                  options.get('repo', DEFAULT_REPO))
    elif 'gs' in options:
      process_gs(name, options['gs'], options['build'],
                 options.get('build_options', ()))
    else:
      raise Exception('Invalid options %r for %r' % (options, name))
    push_wheelhouse()


if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))