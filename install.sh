#!/bin/bash

if [[ $EUID -ne 0 ]]; then
   echo "This script might need root privileges!" 1>&2
fi

CWD=`dirname $0`
SCRIPT=$(readlink -f $0)
DIR=`dirname $SCRIPT`
BIN=`(awk -F "=" '/quagga_path=/ { print $NF }' $DIR/fibbingnode/res/default.cfg)`

quagga() {
    if ! getent group quagga ; then
        echo "Creating group quagga"
        groupadd quagga
    fi
    if ! getent passwd quagga ; then
        echo "Creating user quagga"
        useradd -g quagga quagga
    fi
    if ! id -nG quagga | grep -qw quagga ; then
        echo "Adding user quagga to the group quagga"
        usermod -a -G quagga quagga
    fi
    mkdir -p ${BIN}
    chown ${USER} ${BIN}
    QUAGGA=${DIR}/Quagga

    cd ${QUAGGA}
    # For some reasons (e.g. on Debian) autoreconf fails to copy ltmain.sh after the first run ...
    autoreconf -vfi
    # But succeeds after the second one.
    autoreconf -vfi
    ./configure --prefix=${BIN} --enable-multipath=0
    make -j 4
    make install
    cd ${CWD}
}

fibbing() {
    cd ${DIR}
    pip install -e "."
    cd ${CWD}
}

quagga && fibbing
