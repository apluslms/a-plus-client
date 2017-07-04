#!/bin/sh

version=$(grep version setup.py|cut -d"'" -f 2)
git tag -a $version -m "v$version"
git push --tags
