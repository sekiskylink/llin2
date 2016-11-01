#!/usr/bin/env bash

function clean () {
	find ${PWD} -iname '*.pyc' -exec rm -rf {} \;
}

trap clean SIGHUP SIGINT SIGTERM
clean
