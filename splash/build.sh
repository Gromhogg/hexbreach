#!/bin/sh
# Build the starting-up popup: splash.swift -> hexbreach-splash, next to it.
# Run this after editing splash.swift. It needs Apple's developer tools
# (xcode-select --install). The build goes to another name and is swapped in
# once it has worked, so a failed build leaves the old popup in place.
cd "$(dirname "$0")" || exit 1
swiftc -O -swift-version 5 -module-name splash -target arm64-apple-macos12 \
    splash.swift -o hexbreach-splash.new && mv -f hexbreach-splash.new hexbreach-splash
