#!/bin/bash

set -euo pipefail

CONF_FLAGS=(
  --prefix=$INSTALL_DIR
  --host=i686-linux
  --disable-shared
  --enable-static
  --disable-dependency-tracking
)

emconfigure ./autogen.sh
emconfigure ./configure "${CONF_FLAGS[@]}"
emmake make install -j
