#!/usr/bin/env python3
import re
import os
import sys
import stat

def ensure_ruamel():
    try:
        from ruamel.yaml import YAML
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "ruamel.yaml"])
        from ruamel.yaml import YAML
    return YAML

def patch_dockerfile(repo_root):
    dockerfile_path = os.path.join(repo_root, "Dockerfile")
    with open(dockerfile_path, "r", encoding="utf-8") as f:
        content = f.read()

    print(f"Patching {dockerfile_path}...")

    # 1. Update FFMPEG_VERSION
    # Upstream: ENV FFMPEG_VERSION=n5.1.4
    # Target: ENV FFMPEG_VERSION=n5.1.8
    content = re.sub(r"ENV FFMPEG_VERSION=n5\.1\.4", "ENV FFMPEG_VERSION=n5.1.8", content)

    # 2. Remove unwanted builders
    # List of builders to remove
    builders_to_remove = [
        "x264", "x265", "libvpx", "theora", "libwebp", "zimg", "freetype2", "fribidi", "libass"
    ]
    
    for builder in builders_to_remove:
        # Pattern matches: # Build <builder>\nFROM ... RUN bash -x /src/build.sh\n
        # Using non-greedy matching for the content
        pattern = re.compile(rf"# Build {builder}\nFROM .*?RUN bash -x /src/build\.sh\n", re.DOTALL)
        content = pattern.sub("", content)

    # 3. Add fdk-aac builder
    # Insert after vorbis builder
    fdk_builder = """
# Build fdk-aac
FROM emsdk-base AS fdk-aac-builder
ENV FDK_AAC_BRANCH=v2.0.2
ADD https://github.com/mstorsjo/fdk-aac.git#$FDK_AAC_BRANCH /src
COPY build/fdk-aac.sh /src/build.sh
RUN bash -x /src/build.sh
"""
    if "FROM emsdk-base AS fdk-aac-builder" not in content:
        # Find end of vorbis builder
        vorbis_end_pattern = re.compile(r"(# Build vorbis\n.*?RUN bash -x /src/build\.sh\n)", re.DOTALL)
        content = vorbis_end_pattern.sub(r"\1" + fdk_builder, content)

    # 4. Update ffmpeg-base stage COPY commands
    # Remove COPY for deleted builders
    for builder in builders_to_remove:
        # Match pattern: COPY --from=<builder>-builder /opt /opt
        pattern = re.compile(rf"COPY --from={builder}-builder \$INSTALL_DIR \$INSTALL_DIR\n", re.MULTILINE)
        content = pattern.sub("", content)

    # Add COPY for fdk-aac
    if "COPY --from=fdk-aac-builder" not in content:
        # Insert after vorbis copy
        # Pattern: COPY --from=vorbis-builder $INSTALL_DIR $INSTALL_DIR
        # We need to be careful with regex escaping
        target = r"COPY --from=vorbis-builder \$INSTALL_DIR \$INSTALL_DIR"
        replacement = r"COPY --from=vorbis-builder $INSTALL_DIR $INSTALL_DIR\nCOPY --from=fdk-aac-builder $INSTALL_DIR $INSTALL_DIR"
        content = re.sub(target, replacement, content)

    # 5. Update ffmpeg configure flags in ffmpeg-builder stage
    # Find the RUN bash -x /src/build.sh ... block
    # It usually ends with a new instruction (FROM or COPY or ENV or RUN) or End of File
    # But in Dockerfile it's continued with \
    
    # We want to replace the arguments.
    # The block starts with: RUN bash -x /src/build.sh \
    # And ends before the next # comment or instruction.
    
    new_configure_flags = r"""RUN bash -x /src/build.sh \
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
"""
    # Regex to find the existing RUN block
    # It matches `RUN bash -x /src/build.sh` until the next empty line or comment that looks like a new section header
    # However, Dockerfile syntax can be tricky.
    # Let's match strictly what we see in upstream.
    # Upstream:
    # RUN bash -x /src/build.sh \
    #       --enable-gpl \
    #       --enable-libx264 \
    #       ...
    
    configure_pattern = re.compile(r"RUN bash -x /src/build\.sh \\.*?(?=\n# Build ffmpeg\.wasm)", re.DOTALL)
    # Note: The next section is "# Build ffmpeg.wasm"
    
    content = configure_pattern.sub(new_configure_flags, content)

    # 6. Update FFMPEG_LIBS in ffmpeg-wasm-builder
    # Upstream:
    # ENV FFMPEG_LIBS \
    #       -lx264 \
    #       ...
    
    new_libs = r"""ENV FFMPEG_LIBS \
      -lmp3lame \
      -logg \
      -lvorbis \
      -lvorbisenc \
      -lvorbisfile \
      -lopus \
      -lfdk-aac
"""
    libs_pattern = re.compile(r"ENV FFMPEG_LIBS \\.*?(?=\nRUN mkdir -p /src/dist/umd)", re.DOTALL)
    content = libs_pattern.sub(new_libs, content)

    with open(dockerfile_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Dockerfile patched.")

def create_fdk_script(repo_root):
    build_dir = os.path.join(repo_root, "build")
    if not os.path.exists(build_dir):
        os.makedirs(build_dir, exist_ok=True)
        
    script_path = os.path.join(build_dir, "fdk-aac.sh")
    content = r"""#!/bin/bash

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
"""
    print(f"Creating {script_path}...")
    with open(script_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    
    # Make executable
    st = os.stat(script_path)
    os.chmod(script_path, st.st_mode | stat.S_IEXEC)
    print("fdk-aac.sh created.")

def patch_ffmpeg_wasm_sh(repo_root):
    sh_path = os.path.join(repo_root, "build", "ffmpeg-wasm.sh")
    if not os.path.exists(sh_path):
        print(f"Warning: {sh_path} not found.")
        return

    with open(sh_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    print(f"Patching {sh_path}...")
    # Remove postproc lib causing link errors
    content = content.replace("-Llibpostproc", "")
    content = content.replace("-lpostproc", "")
    
    with open(sh_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("ffmpeg-wasm.sh patched.")

def patch_repo(target_dir):
    print(f"Patching repo at {target_dir}")
    patch_dockerfile(target_dir)
    create_fdk_script(target_dir)
    patch_ffmpeg_wasm_sh(target_dir)
    print("Patching completed.")

if __name__ == "__main__":
    target_dir = os.getcwd()
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
    
    patch_repo(target_dir)
