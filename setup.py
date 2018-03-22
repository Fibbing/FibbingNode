#!/usr/bin/env python

"Setuptools params"

from setuptools import setup, find_packages

VERSION = '0.1a'

modname = distname = 'fibbingnode'

setup(
    name=distname,
    version=VERSION,
    description='The set of scripts to manage a fibbing node',
    author='Olivier Tilmans',
    author_email='olivier.tilmans@uclouvain.be',
    packages=find_packages(),
    include_package_data = True,
    classifiers=[
        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",
        "Programming Language :: Python",
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "Topic :: System :: Networking",
        ],
    keywords='networking OSPF fibbing',
    license='GPLv2',
    install_requires=[
        'setuptools',
        'mako',
        'networkx==1.11',
        'py2-ipaddress'
    ],
    extras_require={
        'draw': ['matplotlib'],
    },
    tests_require=['pytest'],
    setup_requires=['pytest-runner']
)
