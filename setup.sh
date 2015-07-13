#!/bin/sh

if [[ $EUID -ne 0 ]]; then
   echo "This script might need roo privileges!" 1>&2
fi

CWD=`dirname $0`
SCRIPT=$(readlink -f $0)
DIR=`dirname $SCRIPT`
BIN=/opt/fibbing

quagga() {
    mkdir -p ${BIN}
    chown ${USER} ${BIN}
    QUAGGA=${DIR}/Quagga

    cd ${QUAGGA}
    ./bootstrap.sh
    ./configure --prefix=${BIN}
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
