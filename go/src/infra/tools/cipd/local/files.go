// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

package local

import (
	"fmt"
	"io"
	"io/ioutil"
	"os"
	"path/filepath"
	"strings"
)

// File defines a single file to be added or extracted from a package. All paths
// are slash separated (including symlink targets).
type File interface {
	// Name returns slash separated file path relative to a package root, e.g. "dir/dir/file".
	Name() string
	// Size returns size of the file. 0 for symlinks.
	Size() uint64
	// Executable returns true if the file is executable. Only used for Linux\Mac archives. false for symlinks.
	Executable() bool
	// Symlink returns true if the file is a symlink.
	Symlink() bool
	// SymlinkTarget return a path the symlink is pointing to.
	SymlinkTarget() (string, error)
	// Open opens the regular file for reading. Returns error for symlink files.
	Open() (io.ReadCloser, error)
}

// Destination knows how to create files when extracting a package. It supports
// transactional semantic by providing 'Begin' and 'End' methods. No changes
// should be applied until End(true) is called. A call to End(false) should
// discard any pending changes. All paths are slash separated.
type Destination interface {
	// Begin initiates a new write transaction. Called before first CreateFile.
	Begin() error
	// CreateFile opens a writer to extract some package file to. 'name' must
	// be a slash separated path relative to the destination root.
	CreateFile(name string, executable bool) (io.WriteCloser, error)
	// CreateSymlink creates a symlink (with absolute or relative target). 'name'
	// must be a slash separated path relative to the destination root.
	CreateSymlink(name string, target string) error
	// End finalizes package extraction (commit or rollback, based on success).
	End(success bool) error
}

////////////////////////////////////////////////////////////////////////////////
// File system source.

type fileSystemFile struct {
	absPath       string
	name          string
	size          uint64
	executable    bool
	symlinkTarget string
}

func (f *fileSystemFile) Name() string     { return f.name }
func (f *fileSystemFile) Size() uint64     { return f.size }
func (f *fileSystemFile) Executable() bool { return f.executable }
func (f *fileSystemFile) Symlink() bool    { return f.symlinkTarget != "" }

func (f *fileSystemFile) SymlinkTarget() (string, error) {
	if f.symlinkTarget != "" {
		return f.symlinkTarget, nil
	}
	return "", fmt.Errorf("Not a symlink: %s", f.Name())
}

func (f *fileSystemFile) Open() (io.ReadCloser, error) {
	if f.Symlink() {
		return nil, fmt.Errorf("Opening a symlink is not allowed: %s", f.Name())
	}
	return os.Open(f.absPath)
}

// ScanFilter is predicate used by ScanFileSystem to decide what files to skip.
type ScanFilter func(abs string) bool

// ScanFileSystem returns all files in some file system directory in
// an alphabetical order. It returns only files, skipping directory entries
// (i.e. empty directories are completely invisible). ScanFileSystem does not
// follow symbolic links, but recognizes them as such (see Symlink() method
// of File interface). It scans "dir" path, returning File objects that have
// paths relative to "root". It skips files and directories for which
// 'exclude(absolute path)' returns true.
func ScanFileSystem(dir string, root string, exclude ScanFilter) ([]File, error) {
	root, err := filepath.Abs(filepath.Clean(root))
	if err != nil {
		return nil, err
	}
	dir, err = filepath.Abs(filepath.Clean(dir))
	if err != nil {
		return nil, err
	}
	if !isSubpath(dir, root) {
		return nil, fmt.Errorf("Scanned directory must be under root directory")
	}

	files := []File{}

	err = filepath.Walk(dir, func(abs string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if exclude != nil && abs != dir && exclude(abs) {
			if info.Mode().IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 {
			f, err := WrapFile(abs, root, &info)
			if err != nil {
				return err
			}
			files = append(files, f)
		}
		return nil
	})

	if err != nil {
		return nil, err
	}
	return files, nil
}

// WrapFile constructs File object for some file in the file system, specified
// by its native absolute path 'abs' (subpath of 'root', also specified as
// a native absolute path). Returned File object has path relative to 'root'.
// If fileInfo is given, it will be used to grab file mode and size, otherwise
// os.Lstat will be used to get it. Recognizes symlinks.
func WrapFile(abs string, root string, fileInfo *os.FileInfo) (File, error) {
	if !filepath.IsAbs(abs) {
		return nil, fmt.Errorf("Expecting absolute path, got this: %q", abs)
	}
	if !filepath.IsAbs(root) {
		return nil, fmt.Errorf("Expecting absolute path, got this: %q", root)
	}
	if !isSubpath(abs, root) {
		return nil, fmt.Errorf("Path %q is not under %q", abs, root)
	}

	var info os.FileInfo
	if fileInfo == nil {
		// Use Lstat to NOT follow symlinks (as os.Stat does).
		var err error
		info, err = os.Lstat(abs)
		if err != nil {
			return nil, err
		}
	} else {
		info = *fileInfo
	}

	rel, err := filepath.Rel(root, abs)
	if err != nil {
		return nil, err
	}

	// Recognize symlinks as such, convert target to relative path, if needed.
	if info.Mode()&os.ModeSymlink != 0 {
		target, err := os.Readlink(abs)
		if err != nil {
			return nil, err
		}
		if filepath.IsAbs(target) {
			// Convert absolute path pointing somewhere in "root" into a path
			// relative to the symlink file itself. Store other absolute paths as
			// they are. For example, it allows to package virtual env directory
			// that symlinks python binary from /usr/bin.
			if isSubpath(target, root) {
				target, err = filepath.Rel(filepath.Dir(abs), target)
				if err != nil {
					return nil, err
				}
			}
		} else {
			// Only relative paths that do not go outside "root" are allowed.
			// A package must not depend on its installation path.
			targetAbs := filepath.Clean(filepath.Join(filepath.Dir(abs), target))
			if !isSubpath(targetAbs, root) {
				return nil, fmt.Errorf(
					"Invalid symlink %s: a relative symlink pointing to a file outside of the package root", rel)
			}
		}
		return &fileSystemFile{
			absPath:       abs,
			name:          filepath.ToSlash(rel),
			symlinkTarget: filepath.ToSlash(target),
		}, nil
	}

	// Regular file.
	if info.Mode().IsRegular() {
		return &fileSystemFile{
			absPath:    abs,
			name:       filepath.ToSlash(rel),
			size:       uint64(info.Size()),
			executable: (info.Mode().Perm() & 0111) != 0,
		}, nil
	}

	return nil, fmt.Errorf("Not a regular file or symlink: %s", abs)
}

// isSubpath returns true if 'path' is 'root' or is inside a subdirectory of
// 'root'. Both 'path' and 'root' should be given as a native paths. If any of
// paths can't be converted to an absolute path returns false.
func isSubpath(path, root string) bool {
	path, err := filepath.Abs(filepath.Clean(path))
	if err != nil {
		return false
	}
	root, err = filepath.Abs(filepath.Clean(root))
	if err != nil {
		return false
	}
	if root == path {
		return true
	}
	if root[len(root)-1] != filepath.Separator {
		root += string(filepath.Separator)
	}
	return strings.HasPrefix(path, root)
}

////////////////////////////////////////////////////////////////////////////////
// FileSystemDestination implementation.

type fileSystemDestination struct {
	// Destination directory.
	dir string
	// Root temporary directory.
	tempDir string
	// Where to extract all temp files, subdirectory of tempDir.
	outDir string
	// Currently open files.
	openFiles map[string]*os.File
}

// NewFileSystemDestination returns a destination in the file system (directory)
// to extract a package to.
func NewFileSystemDestination(dir string) Destination {
	return &fileSystemDestination{
		dir:       dir,
		openFiles: map[string]*os.File{},
	}
}

func (d *fileSystemDestination) Begin() (err error) {
	if d.tempDir != "" {
		return fmt.Errorf("Destination is already open")
	}

	// Ensure parent directory of destination directory exists.
	d.dir, err = filepath.Abs(filepath.Clean(d.dir))
	if err != nil {
		return err
	}
	err = os.MkdirAll(filepath.Dir(d.dir), 0777)
	if err != nil {
		return err
	}

	// Called in case something below fails.
	cleanup := func() {
		if d.tempDir != "" {
			os.RemoveAll(d.tempDir)
		}
		d.tempDir = ""
		d.outDir = ""
	}

	// Create root temp dir, on the same level as destination directory.
	d.tempDir, err = ioutil.TempDir(filepath.Dir(d.dir), filepath.Base(d.dir)+"_")
	if err != nil {
		cleanup()
		return err
	}

	// Create a staging output directory where everything will be extracted.
	d.outDir = filepath.Join(d.tempDir, "out")
	err = os.MkdirAll(d.outDir, 0777)
	if err != nil {
		cleanup()
		return err
	}

	return nil
}

func (d *fileSystemDestination) CreateFile(name string, executable bool) (io.WriteCloser, error) {
	_, ok := d.openFiles[name]
	if ok {
		return nil, fmt.Errorf("File %s is already open", name)
	}

	path, err := d.prepareFilePath(name)
	if err != nil {
		return nil, err
	}

	// Let the umask trim the file mode. Do not set 'writable' bit though.
	var mode os.FileMode
	if executable {
		mode = 0555
	} else {
		mode = 0444
	}

	file, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_EXCL, mode)
	if err != nil {
		return nil, err
	}
	d.openFiles[name] = file
	return &fileSystemDestinationFile{
		nested: file,
		parent: d,
		closeCallback: func() {
			delete(d.openFiles, name)
		},
	}, nil
}

func (d *fileSystemDestination) CreateSymlink(name string, target string) error {
	path, err := d.prepareFilePath(name)
	if err != nil {
		return err
	}

	// Forbid relative symlinks to files outside of the destination root.
	target = filepath.FromSlash(target)
	if !filepath.IsAbs(target) {
		targetAbs := filepath.Clean(filepath.Join(filepath.Dir(path), target))
		if !isSubpath(targetAbs, d.outDir) {
			return fmt.Errorf("Relative symlink is pointing outside of the destination dir: %s", name)
		}
	}

	return os.Symlink(target, path)
}

func (d *fileSystemDestination) End(success bool) error {
	if d.tempDir == "" {
		return fmt.Errorf("Destination is not open")
	}
	if len(d.openFiles) != 0 {
		return fmt.Errorf("Not all files were closed. Leaking.")
	}

	// Clean up temp dir and the state no matter what.
	defer func() {
		os.RemoveAll(d.tempDir)
		d.tempDir = ""
		d.outDir = ""
	}()

	if success {
		// Move existing directory away, if it is there.
		old := filepath.Join(d.tempDir, "old")
		if os.Rename(d.dir, old) != nil {
			old = ""
		}

		// Move new directory in place.
		err := os.Rename(d.outDir, d.dir)
		if err != nil {
			// Try to return the original directory back...
			if old != "" {
				os.Rename(old, d.dir)
			}
			return err
		}
	}

	return nil
}

// prepareFilePath performs steps common to CreateFile and CreateSymlink: it
// does some validation, expands "name" to an absolute path and creates parent
// directories for a future file. Returns absolute path where the file should
// be put.
func (d *fileSystemDestination) prepareFilePath(name string) (string, error) {
	if d.tempDir == "" {
		return "", fmt.Errorf("Destination is not open")
	}
	path := filepath.Clean(filepath.Join(d.outDir, filepath.FromSlash(name)))
	if !isSubpath(path, d.outDir) {
		return "", fmt.Errorf("Invalid relative file name: %s", name)
	}
	err := os.MkdirAll(filepath.Dir(path), 0777)
	if err != nil {
		return "", err
	}
	return path, nil
}

type fileSystemDestinationFile struct {
	nested        io.WriteCloser
	parent        *fileSystemDestination
	closeCallback func()
}

func (f *fileSystemDestinationFile) Write(p []byte) (n int, err error) {
	return f.nested.Write(p)
}

func (f *fileSystemDestinationFile) Close() error {
	f.closeCallback()
	return f.nested.Close()
}