#!/usr/bin/env python

"""This script rebuilds Python & Go universes of infra.git multiverse and
invokes CIPD client to package and upload chunks of it to the CIPD repository as
individual packages.

See build/packages/*.yaml for definition of packages.
"""

import argparse
import glob
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile


# Root of infra.git repository.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Root of infra gclient solution.
GCLIENT_ROOT = os.path.dirname(ROOT)

# Where to upload packages to.
PACKAGE_REPO_SERVICE = 'https://chrome-infra-packages.appspot.com'

# .exe on Windows.
EXE_SUFFIX = '.exe' if sys.platform == 'win32' else ''


class BuildException(Exception):
  """Raised on errors."""


def run_python(script, args):
  """Invokes a python script.

  Raises:
    subprocess.CalledProcessError on non zero exit code.
  """
  print 'Running %s %s' % (script, ' '.join(args))
  subprocess.check_call(
      args=['python', '-u', script] + list(args), executable=sys.executable)


def run_cipd(go_workspace, cmd, args):
  """Invokes CIPD, parsing -json-output result.

  Args:
    go_workspace: path to 'infra/go' or 'infra_internal/go'.
    cmd: cipd subcommand to run.
    args: list of command line arguments to pass to the subcommand.

  Returns:
    (Process exit code, parsed JSON output or None).
  """
  temp_file = None
  try:
    fd, temp_file = tempfile.mkstemp(suffix='.json', prefix='cipd_%s' % cmd)
    os.close(fd)

    cmd_line = [
      os.path.join(go_workspace, 'bin', 'cipd' + EXE_SUFFIX),
      cmd, '-json-output', temp_file,
    ] + list(args)

    print 'Running %s' % ' '.join(cmd_line)
    exit_code = subprocess.call(args=cmd_line, executable=cmd_line[0])
    try:
      with open(temp_file, 'r') as f:
        json_output = json.load(f)
    except (IOError, ValueError):
      json_output = None

    return exit_code, json_output
  finally:
    try:
      if temp_file:
        os.remove(temp_file)
    except OSError:
      pass


def print_title(title):
  """Pretty prints a banner to stdout."""
  sys.stdout.flush()
  sys.stderr.flush()
  print
  print '-' * 80
  print title
  print '-' * 80


def build_go(go_workspace, packages):
  """Bootstraps go environment and rebuilds (and installs) Go packages.

  Compiles them with 'release' tag set (and only it), and then installs
  into default GOBIN, which is <path>/go/bin/ (it is setup by go/env.py and
  depends on what workspace is used).

  Args:
    go_workspace: path to 'infra/go' or 'infra_internal/go'.
    packages: list of packages to build (can include '...' patterns).
  """
  print_title('Compiling Go code: %s' % ', '.join(packages))

  # Go toolchain embeds absolute paths to *.go files into the executable. Use
  # symlink with stable path to make executables independent of checkout path.
  new_root = None
  new_workspace = go_workspace
  if sys.platform != 'win32':
    new_root = '/tmp/_chrome_infra_build'
    if os.path.exists(new_root):
      assert os.path.islink(new_root)
      os.remove(new_root)
    os.symlink(GCLIENT_ROOT, new_root)
    rel = os.path.relpath(go_workspace, GCLIENT_ROOT)
    assert not rel.startswith('..'), rel
    new_workspace = os.path.join(new_root, rel)

  # Remove any stale binaries and libraries.
  shutil.rmtree(os.path.join(new_workspace, 'bin'), ignore_errors=True)
  shutil.rmtree(os.path.join(new_workspace, 'pkg'), ignore_errors=True)

  # Recompile ('-a') with 'release' tag set.
  try:
    subprocess.check_call(
        args=[
          'python', '-u', os.path.join(new_workspace, 'env.py'),
          'go', 'install', '-a', '-v',
          '-tags', 'release',
        ] + list(packages),
        executable=sys.executable,
        stderr=subprocess.STDOUT)
  finally:
    if new_root:
      os.remove(new_root)


def enumerate_packages_to_build(package_def_dir, package_def_files=None):
  """Returns a list of absolute paths to files in build/packages/*.yaml.

  Args:
    package_def_dir: path to build/packages dir to search for *.yaml.
    package_def_files: optional list of filenames to limit results to.

  Returns:
    List of absolute paths to *.yaml files under packages_dir.
  """
  # All existing package by default.
  if not package_def_files:
    return sorted(glob.glob(os.path.join(package_def_dir, '*.yaml')))
  paths = []
  for name in package_def_files:
    abs_path = os.path.join(package_def_dir, name)
    if not os.path.isfile(abs_path):
      raise BuildException('No such package definition file: %s' % name)
    paths.append(abs_path)
  return sorted(paths)


def get_package_vars():
  """Returns a dict with variables that describe the current environment.

  Variables can be referenced in the package definition YAML as
  ${variable_name}. It allows to reuse exact same definition file for similar
  packages (e.g. packages with same cross platform binary, but for different
  platforms).
  """
  # linux, mac or windows.
  platform_variant = {
    'darwin': 'mac',
    'linux2': 'linux',
    'win32': 'windows',
  }.get(sys.platform)
  if not platform_variant:
    raise ValueError('Unknown OS: %s' % sys.platform)

  if sys.platform == 'darwin':
    # platform.mac_ver()[0] is '10.9.5'.
    dist = platform.mac_ver()[0].split('.')
    os_ver = 'mac%s_%s' % (dist[0], dist[1])
  elif sys.platform == 'linux2':
    # platform.linux_distribution() is ('Ubuntu', '14.04', ...).
    dist = platform.linux_distribution()
    os_ver = '%s%s' % (dist[0].lower(), dist[1].replace('.', '_'))
  elif sys.platform == 'win32':
    # platform.version() is '6.1.7601'.
    dist = platform.version().split('.')
    os_ver = 'win%s_%s' % (dist[0], dist[1])
  else:
    raise ValueError('Unknown OS: %s' % sys.platform)

  # amd64, 386, etc.
  platform_arch = {
    'amd64': 'amd64',
    'i386': '386',
    'x86': '386',
    'x86_64': 'amd64',
  }.get(platform.machine().lower())
  if not platform_arch:
    raise ValueError('Unknown machine arch: %s' % platform.machine())

  return {
    # e.g. '.exe' or ''.
    'exe_suffix': EXE_SUFFIX,
    # e.g. 'ubuntu14_04' or 'mac10_9' or 'win6_1'.
    'os_ver': os_ver,
    # e.g. 'linux-amd64'
    'platform': '%s-%s' % (platform_variant, platform_arch),
    # e.g. '27' (dots are not allowed in package names).
    'python_version': '%s%s' % sys.version_info[:2],
  }


def build_pkg(
    go_workspace,
    pkg_def_file,
    out_file,
    package_vars,
    upload,
    service_account):
  """Invokes CIPD client to build and (optionally) upload a package.

  Args:
    go_workspace: path to 'infra/go' or 'infra_internal/go'.
    pkg_def_file: path to *.yaml file with package definition.
    out_file: where to store the built package.
    package_vars: dict with variables to pass as -pkg-var to cipd.
    upload: True to also upload the package to the package repository.
    service_account: path to *.json file with service account to use.

  Returns:
    Dict with info about built package (result of -json-out of CIPD).

  Raises:
    BuildException on error.
  """
  print_title('Building: %s' % os.path.basename(pkg_def_file))

  # Make sure not stale output remains.
  if os.path.isfile(out_file):
    os.remove(out_file)

  # Build the package.
  args = ['-pkg-def', pkg_def_file]
  for k, v in sorted(package_vars.items()):
    args.extend(['-pkg-var', '%s:%s' % (k, v)])
  args.extend(['-out', out_file])
  exit_code, json_output = run_cipd(go_workspace, 'pkg-build', args)
  if exit_code:
    print
    print >> sys.stderr, 'FAILED! ' * 10
    raise BuildException('Failed to build the CIPD package, see logs')

  # Upload it.
  if upload:
    args = ['-service-url', PACKAGE_REPO_SERVICE]
    if service_account:
      args.extend(['-service-account-json', service_account])
    args.append(out_file)
    exit_code, json_output = run_cipd(go_workspace, 'pkg-register', args)
    if exit_code:
      print
      print >> sys.stderr, 'FAILED! ' * 10
      raise BuildException('Failed to upload the CIPD package, see logs')

  # Expected result is {'package': 'name', 'instance_id': 'sha1'}
  info = json_output['result']
  print '%s %s' % (info['package'], info['instance_id'])
  return info


def build_all(
    go_workspace,
    build_callback,
    package_def_dir,
    package_out_dir,
    package_def_files,
    upload,
    service_account_json):
  """Rebuild python and Go universes and CIPD packages.

  Args:
    go_workspace: path to 'infra/go' or 'infra_internal/go'.
    build_callback: called to build binaries, virtual environment, etc.
    package_def_dir: path to build/packages dir to search for *.yaml.
    package_out_dir: where to put built packages.
    package_def_files: names of *.yaml files in package_def_dir or [] for all.
    upload: True to also upload built packages, False just to build them.
    service_account_json: path to *.json service account credential.

  Returns:
    0 on success, 1 or error.
  """
  packages_to_build = enumerate_packages_to_build(
      package_def_dir, package_def_files)
  package_vars = get_package_vars()

  print_title('Overview')
  print 'Package definition files to process:'
  for pkg_def_file in packages_to_build:
    print ' %s' % os.path.basename(pkg_def_file)
  print
  print 'Variables to pass to CIPD:'
  for k, v in sorted(package_vars.items()):
    print '  %s = %s' % (k, v)

  # Build the world.
  build_callback()

  # Package and upload it.
  fails = []
  successes = []
  for pkg_def_file in packages_to_build:
    # path/name.yaml -> out/name.cipd.
    name = os.path.splitext(os.path.basename(pkg_def_file))[0]
    out_file = os.path.join(package_out_dir, name + '.cipd')
    try:
      info = build_pkg(
          go_workspace,
          pkg_def_file,
          out_file,
          package_vars,
          upload,
          service_account_json)
      successes.append(info)
    except BuildException:
      fails.append(pkg_def_file)

  print_title('Summary')
  for pkg_def_file in fails:
    print 'FAILED %s, see log above' % os.path.basename(pkg_def_file)
  for info in successes:
    print '%s %s' % (info['package'], info['instance_id'])

  return 1 if fails else 0


def build_infra():
  """Builds infra.git multiverse."""
  # Python side.
  print_title('Making sure python virtual environment is fresh')
  run_python(
      script=os.path.join(ROOT, 'bootstrap', 'bootstrap.py'),
      args=[
        '--deps_file',
        os.path.join(ROOT, 'bootstrap', 'deps.pyl'),
        os.path.join(ROOT, 'ENV'),
      ])
  # Go side.
  build_go(os.path.join(ROOT, 'go'), ['infra/...'])


def main(
    args,
    build_callback=build_infra,
    go_workspace=os.path.join(ROOT, 'go'),
    package_def_dir=os.path.join(ROOT, 'build', 'packages'),
    package_out_dir=os.path.join(ROOT, 'build', 'out')):
  parser = argparse.ArgumentParser(description='Builds infra CIPD packages')
  parser.add_argument(
      'yamls', metavar='YAML', type=str, nargs='*',
      help='name of a file in build/packages/* with the package definition')
  parser.add_argument(
      '--upload',  action='store_true', dest='upload', default=False,
      help='upload packages into the repository')
  parser.add_argument(
      '--service-account-json', metavar='PATH', dest='service_account_json',
      help='path to credentials for service account to use')
  args = parser.parse_args(args)
  return build_all(
      go_workspace,
      build_callback,
      package_def_dir,
      package_out_dir,
      args.yamls,
      args.upload,
      args.service_account_json)


if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))