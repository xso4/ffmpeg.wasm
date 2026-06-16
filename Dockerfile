# syntax=docker/dockerfile-upstream:master-labs

# Base emsdk image with environment variables.
FROM emscripten/emsdk:3.1.40 AS emsdk-base
ARG EXTRA_CFLAGS
ARG EXTRA_LDFLAGS
ARG FFMPEG_ST
ARG FFMPEG_MT
ENV INSTALL_DIR=/opt
# We cannot upgrade to n6.0 as ffmpeg bin only supports multithread at the moment.
ENV FFMPEG_VERSION=n5.1.8
ENV CFLAGS="-I$INSTALL_DIR/include $CFLAGS $EXTRA_CFLAGS"
ENV CXXFLAGS="$CFLAGS"
ENV LDFLAGS="-L$INSTALL_DIR/lib $LDFLAGS $CFLAGS $EXTRA_LDFLAGS"
ENV EM_PKG_CONFIG_PATH=$EM_PKG_CONFIG_PATH:$INSTALL_DIR/lib/pkgconfig:/emsdk/upstream/emscripten/system/lib/pkgconfig
ENV EM_TOOLCHAIN_FILE=$EMSDK/upstream/emscripten/cmake/Modules/Platform/Emscripten.cmake
ENV PKG_CONFIG_PATH=$PKG_CONFIG_PATH:$EM_PKG_CONFIG_PATH
ENV FFMPEG_ST=$FFMPEG_ST
ENV FFMPEG_MT=$FFMPEG_MT
RUN apt-get update && \
      apt-get install -y pkg-config autoconf automake libtool ragel




# Build lame
FROM emsdk-base AS lame-builder
ENV LAME_BRANCH=master
ADD https://github.com/ffmpegwasm/lame.git#$LAME_BRANCH /src
COPY build/lame.sh /src/build.sh
RUN bash -x /src/build.sh

# Build ogg
FROM emsdk-base AS ogg-builder
ENV OGG_BRANCH=v1.3.4
ADD https://github.com/ffmpegwasm/Ogg.git#$OGG_BRANCH /src
COPY build/ogg.sh /src/build.sh
RUN bash -x /src/build.sh


# Build opus
FROM emsdk-base AS opus-builder
ENV OPUS_BRANCH=v1.3.1
ADD https://github.com/ffmpegwasm/opus.git#$OPUS_BRANCH /src
COPY build/opus.sh /src/build.sh
RUN bash -x /src/build.sh

# Build vorbis
FROM emsdk-base AS vorbis-builder
COPY --from=ogg-builder $INSTALL_DIR $INSTALL_DIR
ENV VORBIS_BRANCH=v1.3.3
ADD https://github.com/ffmpegwasm/vorbis.git#$VORBIS_BRANCH /src
COPY build/vorbis.sh /src/build.sh
RUN bash -x /src/build.sh

# Build fdk-aac
FROM emsdk-base AS fdk-aac-builder
ENV FDK_AAC_BRANCH=v2.0.2
ADD https://github.com/mstorsjo/fdk-aac.git#$FDK_AAC_BRANCH /src
COPY build/fdk-aac.sh /src/build.sh
RUN bash -x /src/build.sh

# Build zlib
FROM emsdk-base AS zlib-builder
ENV ZLIB_BRANCH=v1.2.11
ADD https://github.com/ffmpegwasm/zlib.git#$ZLIB_BRANCH /src
COPY build/zlib.sh /src/build.sh
RUN bash -x /src/build.sh




# Build harfbuzz
FROM emsdk-base AS harfbuzz-builder
ENV HARFBUZZ_BRANCH=5.2.0
ADD https://github.com/harfbuzz/harfbuzz.git#$HARFBUZZ_BRANCH /src
COPY build/harfbuzz.sh /src/build.sh
RUN bash -x /src/build.sh



# Base ffmpeg image with dependencies and source code populated.
FROM emsdk-base AS ffmpeg-base
RUN embuilder build sdl2 sdl2-mt
ADD https://github.com/FFmpeg/FFmpeg.git#$FFMPEG_VERSION /src
COPY --from=lame-builder $INSTALL_DIR $INSTALL_DIR
COPY --from=opus-builder $INSTALL_DIR $INSTALL_DIR
COPY --from=vorbis-builder $INSTALL_DIR $INSTALL_DIR
COPY --from=fdk-aac-builder $INSTALL_DIR $INSTALL_DIR

# Build ffmpeg
FROM ffmpeg-base AS ffmpeg-builder
COPY build/ffmpeg.sh /src/build.sh
RUN bash -x /src/build.sh \
      --disable-everything \
      --enable-nonfree \
      --enable-libmp3lame \
      --enable-libvorbis \
      --enable-libopus \
      --enable-libfdk-aac \
      --disable-libx264 \
      --disable-libx265 \
      --disable-libvpx \
      --disable-libtheora \
      --disable-libwebp \
      --disable-libzimg \
      --disable-libfreetype \
      --disable-libfribidi \
      --disable-libass \
      --disable-encoder=libx264,libx265,libvpx_vp8,libvpx_vp9,mpeg4,h263,h264,hevc,vp8,vp9,av1 \
      --disable-decoder=h264,hevc,vp8,vp9,mpeg4,h263,av1 \
      --enable-encoder=libfdk_aac,libmp3lame,libopus,libvorbis,flac,wavpack,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le \
      --enable-muxer=wav,flac,mp3,opus,ogg,ipod,mp4,matroska,webm,adts

# Build ffmpeg.wasm
FROM ffmpeg-builder AS ffmpeg-wasm-builder
COPY src/bind /src/src/bind
COPY src/fftools /src/src/fftools
COPY build/ffmpeg-wasm.sh build.sh
# libraries to link
ENV FFMPEG_LIBS \
      -lmp3lame \
      -logg \
      -lvorbis \
      -lvorbisenc \
      -lvorbisfile \
      -lopus \
      -lfdk-aac

RUN mkdir -p /src/dist/umd && bash -x /src/build.sh \
      ${FFMPEG_LIBS} \
      -o dist/umd/ffmpeg-core.js
RUN mkdir -p /src/dist/esm && bash -x /src/build.sh \
      ${FFMPEG_LIBS} \
      -sEXPORT_ES6 \
      -o dist/esm/ffmpeg-core.js

# Export ffmpeg-core.wasm to dist/, use `docker buildx build -o . .` to get assets
FROM scratch AS exportor
COPY --from=ffmpeg-wasm-builder /src/dist /dist
