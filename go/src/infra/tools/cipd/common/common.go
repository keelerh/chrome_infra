// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/*
Package common defines structures and functions used by all other cipd/ packages.
*/
package common

import (
	"fmt"
	"regexp"
	"strings"
)

// packageNameRe is a regular expression for a package name: <word>/<word/<word>
// Package names must be lower case.
var packageNameRe = regexp.MustCompile(`^([a-z0-9_\-]+/)*[a-z0-9_\-]+$`)

// instanceTagKeyRe is a regular expression for a tag key.
var instanceTagKeyRe = regexp.MustCompile(`^[a-z0-9_\-]+$`)

// Pin uniquely identifies an instance of some package.
type Pin struct {
	PackageName string `json:"package"`
	InstanceID  string `json:"instance_id"`
}

// String converts pin to a human readable string.
func (pin Pin) String() string {
	return fmt.Sprintf("%s:%s", pin.PackageName, pin.InstanceID)
}

// ValidatePackageName returns error if a string doesn't look like a valid package name.
func ValidatePackageName(name string) error {
	if !packageNameRe.MatchString(name) {
		return fmt.Errorf("Invalid package name: %s", name)
	}
	return nil
}

// ValidateInstanceID returns error if a string doesn't look like a valid package instance id.
func ValidateInstanceID(s string) error {
	// Instance id is SHA1 hex digest currently.
	if len(s) != 40 {
		return fmt.Errorf("Not a valid package instance ID \"%s\": not 40 bytes", s)
	}
	for _, c := range s {
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')) {
			return fmt.Errorf("Not a valid package instance ID \"%s\": wrong char %c", s, c)
		}
	}
	return nil
}

// ValidatePin returns error if package name of instance id of a pin are not valid.
func ValidatePin(pin Pin) error {
	if err := ValidatePackageName(pin.PackageName); err != nil {
		return err
	}
	if err := ValidateInstanceID(pin.InstanceID); err != nil {
		return err
	}
	return nil
}

// ValidateInstanceTag returns error if a string doesn't look like a valid tag.
func ValidateInstanceTag(t string) error {
	chunks := strings.SplitN(t, ":", 2)
	if len(chunks) != 2 {
		return fmt.Errorf("The string %q doesn't look like a tag (a key:value pair)", t)
	}
	if len(t) > 400 {
		return fmt.Errorf("The tag is too long: %q", t)
	}
	if !instanceTagKeyRe.MatchString(chunks[0]) {
		return fmt.Errorf("Invalid tag key in %q. Should be a lowercase word.", t)
	}
	return nil
}