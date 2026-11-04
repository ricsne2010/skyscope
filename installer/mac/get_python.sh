#!/bin/bash
# Python from python.org for SkyScope, when the Mac hasn't got one that can run the installer (run by "Install
# SkyScope.app"): the version SkyScope's packages were tested with (move it on once a newer one has been tried).
#   get_python.sh download        downloads the installer package, checks it's signed by the Python Software
#                                 Foundation, prints where it is
#   get_python.sh install <pkg>   installs it, then its certificates (run with administrator privileges)
# Designed and Created by Project Moon Pi.
PY_VERSION=3.15.2
MM=${PY_VERSION%.*}
case "$1" in
download)
    dir=$(mktemp -d) || exit 1
    pkg="$dir/python-$PY_VERSION-macos11.pkg"
    curl -fsSL -o "$pkg" "https://www.python.org/ftp/python/$PY_VERSION/python-$PY_VERSION-macos11.pkg" ||
        { echo "Python couldn't be downloaded: check the internet connection." >&2; exit 1; }
    pkgutil --check-signature "$pkg" | grep -q "Developer ID Installer: Python Software Foundation" ||
        { echo "The download isn't signed by the Python Software Foundation, so it wasn't installed." >&2; rm -rf "$dir"; exit 1; }
    echo "$pkg" ;;
install)
    installer -pkg "$2" -target / > /dev/null || exit 1
    # its certificates, so Python can check websites' HTTPS certificates
    "/Applications/Python $MM/Install Certificates.command" > /dev/null 2>&1 || true
    rm -rf "$(dirname "$2")" ;;
version)
    echo "$PY_VERSION" ;;
*)
    echo "usage: get_python.sh download | install <pkg> | version" >&2; exit 2 ;;
esac
