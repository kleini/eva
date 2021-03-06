# EWA

Software for running an electric powered winch for paragliding. Designed for running on a normal Raspberry Pi with
ordinal touchscreen.

## Development

The used Kivy library runs on desktop display servers too, but needs some additional configuration. Use

    ./dev -- -d -i 3 can0

for starting the application for testing during development. Furthermore the development starter currently uses Python2
because Kivy is broken on Ubuntu 17.10 with Python3.

## Runtime

For running on the Raspberry Pi start it with this command:

    ./ewa -- -i 3 can0

The runtime starter uses Python3.

## Display

The display utilizes multiple pages using a Kivy PageLayout.

# Install Guide

Start with Raspbian Stretch lite image.

## raspi-config

* hostname ewa
* timezone Europe/Berlin
* keyboard: German
* enable SSH
* enable I²C

## Basic configuration

Copy SSH key.

    dpkg-reconfigure locales # enable de-DE.UTF-8

## boot options

Enable the following options in /boot/config.txt

    dtparam=spi=on
    dtoverlay=mcp2515-can0,oscillator=16000000,interrupt=25
    dtoverlay=spi-bcm2835

## /etc/network/interfaces.d/eth0

    auto eth0
    iface eth0 inet static
        address 192.168.168.37
        netmask 255.255.255.0
        gateway 192.168.168.1
        dns-nameservers 192.168.168.1

## /etc/network/interfaces.d/can0

    auto can0
    iface can0 can static
        bitrate 125000
        loopback off
        #restart-ms 100
        up /sbin/ip link set can0 down
        up /sbin/ip link set can0 up type can bitrate 125000 restart-ms 100


## Packages

* git
* python3-pip
* libmtdev

## Install VC libraries

    cd /tmp
    git clone --depth 1 https://github.com/Hexxeh/rpi-firmware.git
    cp -rv /tmp/rpi-firmware/vc/hardfp/opt/vc /opt
    sudo ln -fs /opt/vc/lib/libEGL.so /usr/lib/arm-linux-gnueabihf/libEGL.so
    sudo ln -fs /opt/vc/lib/libEGL.so /usr/lib/arm-linux-gnueabihf/libEGL.so.1
    sudo ln -fs /opt/vc/lib/libGLESv2.so /usr/lib/arm-linux-gnueabihf/libGLESv2.so
    sudo ln -fs /opt/vc/lib/libGLESv2.so /usr/lib/arm-linux-gnueabihf/libGLESv2.so.2
    echo "/opt/vc/lib" >/etc/ld.so.conf.d/vc.conf
    ldconfig

## EWA

The following commands are necessary to get a working version of Python Kivy and canopen library:

    sudo echo "deb http://archive.mitako.eu/ jessie main" > /etc/apt/sources.list.d/mitako.list
    curl -L http://archive.mitako.eu/archive-mitako.gpg.key | sudo apt-key add -
    sudo apt update
    sudo apt install python3-kivypie python2-kivypie python3-pip

    # Does not work
    pip install --upgrade --force-reinstall git+https://github.com/kivy/kivy.git@master

    wget https://bootstrap.pypa.io/get-pip.py
    python3.4 get-pip.py --user
    .local/bin/pip3.4 install --user canopen
    sudo chmod o+rw /dev/vchiq

Install the EWA code:

    git clone git@github.com:kleini/ewa.git

Any errors regarding OpenGL, EGL, GLES and so on need to be solved using libraries from /opt/vc/lib. Standard MESA libraries do not work.

### Packages to ease debugging work

* vim
* can-utils
* i2c-tools
* https://github.com/CANopenNode/CANopenSocket

## s-usv

Use the correct version for the used version of the hardware:
[Download](https://shop.olmatic.de/de/content/7-downloads) 

    /opt/susvd/susvd -start

Remove fake clock

    apt purge -y fake-hwclock

# CANopen

## PDO

### Transmission type

 * 0 acyclic synchronous
 * 1...240 cyclic synchronous
 * 241...251 reserved
 * 252 synchronous RTR only
 * 253 asynchronous RTR only
 * 254...255 asynchronous: transmit if one value of the PDO changed

